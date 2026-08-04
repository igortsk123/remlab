"""Компонент 3: Python-мозг расчёта. Принимает решения и считает размеры + confidence.
OpenCV дал инструменты (точные пиксели/поза) — ЗДЕСЬ рождаются числа и бизнес-логика."""
import cv2, numpy as np

class Solver:
    def __init__(self, img, a4_corners, fov_deg, ceiling_cm=None):
        self.H,self.W=img.shape[:2]; self.ceiling=ceiling_cm
        obj=np.array([[0,29.7,0],[21,29.7,0],[21,0,0],[0,0,0]],float)
        fy=(self.H/2)/np.tan(np.radians(fov_deg)/2)
        self.K=np.array([[fy,0,self.W/2],[0,fy,self.H/2],[0,0,1.]])
        _,rv,tv=cv2.solvePnP(obj,np.array(a4_corners,float),self.K,None,flags=cv2.SOLVEPNP_IPPE)
        R,_=cv2.Rodrigues(rv); self.R=R; self.C=(-R.T@tv).ravel(); self.Ki=np.linalg.inv(self.K)
        self.cam_h=float(self.C[2])
    def ray(self,u,v): return self.R.T@(self.Ki@np.array([float(u),float(v),1.]))
    def floor(self,u,v): d=self.ray(u,v); t=-self.C[2]/d[2]; return self.C+t*d
    def on_facet(self,u,v,A,B):
        n=np.cross(B-A,[0,0,1.]); d=self.ray(u,v); t=np.dot(n,A-self.C)/np.dot(n,d); return self.C+t*d

    def solve_walls(self, edges):
        """edges: [{label,coords:[[x,y],[x,y]],conf,refined,visibility}] → длины стен по полу + решения."""
        out=[]
        for e in edges:
            (a,b)=e["coords"]; A=self.floor(*a); B=self.floor(*b)
            L=float(np.linalg.norm(A-B))
            conf=e["conf"]*(1.0 if e.get("refined") else 0.6)
            if e.get("visibility") in ("mostly_occluded","unclear"): conf*=0.5
            flags=[]
            if not e.get("refined"): flags.append("низ перекрыт/не уточнён")
            if L>700 or L<20: flags.append("длина неправдоподобна"); conf*=0.4
            out.append({"label":e["label"],"len_cm":round(L),"confidence":round(conf,2),
                        "floor_ab_cm":[A[:2].round().tolist(),B[:2].round().tolist()],"flags":flags,
                        "draw":[list(map(int,a)),list(map(int,b))]})
        return out

    def solve_window(self, name, box, facet_edge, occluded=False):
        """Решение: окно на плоскости грани facet_edge → Ш×В + подоконник + бизнес-проверки."""
        (a,b)=facet_edge["coords"]; A=self.floor(*a); B=self.floor(*b)
        x1,y1,x2,y2=box; corners=[(x1,y1),(x2,y1),(x2,y2),(x1,y2)]  # TL,TR,BR,BL
        P=[self.on_facet(u,v,A,B) for u,v in corners]
        w=(np.linalg.norm(P[1][:2]-P[0][:2])+np.linalg.norm(P[2][:2]-P[3][:2]))/2
        h=(abs(P[0][2]-P[3][2])+abs(P[1][2]-P[2][2]))/2
        sill=min(P[2][2],P[3][2]); top=max(P[0][2],P[1][2])
        conf=facet_edge["conf"]*(1.0 if facet_edge.get("refined") else 0.6)
        flags=[]
        # БИЗНЕС-ПРАВИЛА (это и есть «мозг»):
        if occluded: conf*=0.6; flags.append("основание грани перекрыто")
        if not (30<=w<=320): flags.append(f"ширина вне нормы"); conf*=0.5
        if not (40<=h<=260): flags.append("высота вне нормы"); conf*=0.5
        if self.ceiling and top>self.ceiling+15:
            flags.append(f"верх {round(top)}см конфликтует с потолком {self.ceiling}"); conf*=0.5
        if sill<0: flags.append("подоконник ниже пола?"); conf*=0.4
        return {"label":name,"w_cm":round(w),"h_cm":round(h),"sill_cm":round(sill),
                "top_cm":round(top),"confidence":round(min(conf,0.95),2),"flags":flags,"box":box}

    def room_bbox(self, edges):
        """Габарит видимой части комнаты по полу (решение: bounding по floor-точкам стен)."""
        pts=[]
        for e in edges:
            for p in e["coords"]: pts.append(self.floor(*p)[:2])
        pts=np.array(pts)
        return {"visible_span_x_cm":round(float(pts[:,0].max()-pts[:,0].min())),
                "visible_span_y_cm":round(float(pts[:,1].max()-pts[:,1].min()))}
