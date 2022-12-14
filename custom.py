import jittor as jt
from jittor.dataset import Dataset 

import os 
from PIL import Image
import numpy as np 
from numpy import random as nprandom
from jdet.utils.registry import DATASETS
from jdet.models.boxes.box_ops import rotated_box_to_bbox_np
from .transforms import Compose
from pycocotools.coco import COCO
import copy

@DATASETS.register_module()
class CustomDataset(Dataset):
    '''
    Annotation format:
    [
        {
            'filename': 'a.jpg',
            'width': 1280,
            'height': 720,
            'ann': {
                'bboxes': <np.ndarray> (n, 5),
                'labels': <np.ndarray> (n, ),
                'bboxes_ignore': <np.ndarray> (k, 5), (optional field)
                'labels_ignore': <np.ndarray> (k, 5) (optional field)
            }
        },
        ...
    ]
    '''
    CLASSES = None
    def __init__(self,images_dir=None,annotations_file=None,dataset_dir=None,transforms=None,batch_size=1,num_workers=0,shuffle=False,drop_last=False,filter_empty_gt=True,Mix_Up=False,filter_min_size=-1, Mix_Up_prob = 0.3):
        super(CustomDataset,self).__init__(batch_size=batch_size,num_workers=num_workers,shuffle=shuffle,drop_last=drop_last)
        if (dataset_dir is not None):
            assert(images_dir is None)
            assert(annotations_file is None)
            self.images_dir = os.path.abspath(os.path.join(dataset_dir, "images")) 
            self.annotations_file = os.path.abspath(os.path.join(dataset_dir, "labels.pkl"))
        else:
            assert(images_dir is not None)
            assert(annotations_file is not None)
            self.images_dir = os.path.abspath(images_dir) 
            self.annotations_file = os.path.abspath(annotations_file)
        self.Mix_Up_prob = Mix_Up_prob
        self.Mix_Up =Mix_Up
        self.transforms = Compose(transforms)
        self.trans_list = transforms
        self.img_infos = jt.load(self.annotations_file)
        if filter_empty_gt:
            self.img_infos = self._filter_imgs(filter_min_size)
        self.total_len = len(self.img_infos)

    def _filter_imgs(self, min_size):
        return [img_info for img_info in self.img_infos
                if (len(img_info["ann"]["bboxes"])>0 and min(img_info['width'], img_info['height'])>=min_size) ]

    def _read_ann_info(self,idx):
        while True:
            img_info = self.img_infos[idx]
            if len(img_info["ann"]["bboxes"])>0:
                break
            idx = np.random.choice(np.arange(self.total_len))
        anno = img_info["ann"]

        img_path = os.path.join(self.images_dir, img_info["filename"])
        image = Image.open(img_path).convert("RGB")

        width,height = image.size 
        assert width == img_info['width'] and height == img_info["height"],"image size is different from annotations"

        hboxes,polys = rotated_box_to_bbox_np(anno["bboxes"])
        hboxes_ignore,polys_ignore = rotated_box_to_bbox_np(anno["bboxes_ignore"])

        ann = dict(
            rboxes=anno['bboxes'].astype(np.float32),
            hboxes=hboxes.astype(np.float32),
            polys =polys.astype(np.float32),
            labels=anno['labels'].astype(np.int32),
            rboxes_ignore=anno['bboxes_ignore'].astype(np.float32),
            hboxes_ignore=hboxes_ignore,
            polys_ignore = polys_ignore,
            classes=self.CLASSES,
            ori_img_size=(width,height),
            img_size=(width,height),
            scale_factor=1.0,
            filename =  img_info["filename"],
            img_file = img_path)
        return image,ann

    def collate_batch(self,batch):
        imgs = []
        anns = []
        max_width = 0
        max_height = 0
        for image,ann in batch:
            height,width = image.shape[-2],image.shape[-1]
            max_width = max(max_width,width)
            max_height = max(max_height,height)
            imgs.append(image)
            anns.append(ann)
        N = len(imgs)
        batch_imgs = np.zeros((N,3,max_height,max_width),dtype=np.float32)
        for i,image in enumerate(imgs):
            batch_imgs[i,:,:image.shape[-2],:image.shape[-1]] = image
        
        return batch_imgs,anns 

    def __getitem__(self, idx):
        if "BATCH_IDX" in os.environ:
            idx = int(os.environ['BATCH_IDX'])

        if self.Mix_Up:
            idx2 = np.random.choice(np.arange(self.total_len))
            image, anno = self.Mix_Up_im(idx, idx2, prob = self.Mix_Up_prob)
        else:
            image, anno = self._read_ann_info(idx)
        
        if self.transforms is not None:
            image, anno = self.transforms(image, anno)

        return image, anno 

    def evaluate(self,results,work_dir,epoch,logger=None):
        raise NotImplementedError 

    def Mix_Up_im(self, id1, id2, prob=0.3):
        if nprandom.uniform(0, 1) > prob:
            image1, anno1 = self._read_ann_info(id1)
            return image1, anno1
        image1, anno1 = self._read_ann_info(id1)
        image2, anno2 = self._read_ann_info(id2)
        image = Image.blend(image1, image2, 0.5)
        anno = mix_ann(anno1, anno2)
        return image, anno
def mix_ann(anno1, anno2):
    anno1['rboxes']=np.r_[anno1['rboxes'], anno2['rboxes']]
    anno1['hboxes']=np.r_[anno1['hboxes'], anno2['hboxes']]
    anno1['polys']=np.r_[anno1['polys'], anno2['polys']]
    anno1['labels']=np.r_[anno1['labels'], anno2['labels']]
    return anno1


MIX_NEED = ['Mix_Up', 'copypaste', 'RMosaic']
def need_mix(trans_list):
    for dic in trans_list:
        for k in dic.keys():
            if dic[k] in MIX_NEED:
                return True
    return False