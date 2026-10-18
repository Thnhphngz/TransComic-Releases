"""Namespaced settings persistence; no translation schema migration."""
from dataclasses import asdict
import json
from .media import MediaGroup


class GroupManager:
    def __init__(self,store):
        self.store=store
        data=json.loads(store.setting('capcut_workspace_v1','{"groups":[]}'))
        if not isinstance(data,dict):raise ValueError('Dữ liệu nhóm CapCut không hợp lệ')
        self.groups=[MediaGroup(**row) for row in data.get('groups',[])]
        if any(g.image_sort not in ('name','created') for g in self.groups):raise ValueError('Chế độ sắp ảnh đã lưu không hợp lệ')
        if len({g.id for g in self.groups})!=len(self.groups):raise ValueError('Trùng ID nhóm đã lưu')
        self.mode=data.get('mode','separate');self.output=data.get('output','');self.name=data.get('name','TransComic')
        self.part_count=data.get('part_count',2)
        if type(self.part_count) is not int or self.part_count<2:self.part_count=2
        names=data.get('custom_names',{})
        self.custom_names={str(int(k)):v for k,v in names.items() if str(k).isascii() and str(k).isdigit() and int(k)>0 and isinstance(v,str)} if isinstance(names,dict) else {}

    def save(self):
        self.store.set_setting('capcut_workspace_v1',json.dumps(dict(groups=[asdict(g) for g in self.groups],mode=self.mode,output=self.output,name=self.name,part_count=self.part_count,custom_names=self.custom_names),ensure_ascii=False))

    def set_part_name(self,number,name):
        old=dict(self.custom_names)
        if name is None:self.custom_names.pop(str(number),None)
        else:self.custom_names[str(number)]=name
        try:self.save()
        except Exception:self.custom_names=old;raise

    def add(self,group):self.groups.append(group);self.save()
    def add_many(self,groups):
        groups=tuple(groups)
        if not groups:raise ValueError('Chưa có cặp thư mục')
        if len({g.id for g in (*self.groups,*groups)})!=len(self.groups)+len(groups):raise ValueError('Trùng ID nhóm')
        old=self.groups
        self.groups=[*old,*groups]
        try:self.save()
        except Exception:self.groups=old;raise
    def replace(self,group):
        i=next(i for i,g in enumerate(self.groups) if g.id==group.id);self.groups[i]=group;self.save()
    def remove(self,id):self.groups=[g for g in self.groups if g.id!=id];self.save()
    def clear(self):
        """Remove workspace entries only; preserve options and roll back on save failure."""
        old=self.groups;self.groups=[]
        try:self.save()
        except Exception:self.groups=old;raise
    def move(self,id,delta):
        i=next(i for i,g in enumerate(self.groups) if g.id==id);j=i+delta
        if 0<=j<len(self.groups):self.groups[i],self.groups[j]=self.groups[j],self.groups[i];self.save()
