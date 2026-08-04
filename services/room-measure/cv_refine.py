"""Компонент 2: OpenCV уточняет пиксельную геометрию вокруг seed'ов Gemini.
НЕ понимает смысла — только притягивает точки к реальным рёбрам (Canny/Hough/subpix)."""
import cv2, numpy as np

def refine_a4(img):
    """Независимый детект A4 (Otsu) + субпиксельное уточнение углов. Seed Gemini НЕ нужен."""
    H,W=img.shape[:2]; y0=int(0.78*H)
    roi=img[y0:H]; g=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
    _,th=cv2.threshold(cv2.GaussianBlur(g,(5,5),0),0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    th=cv2.morphologyEx(th,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    cnts,_=cv2.findContours(th,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    best=None;ba=0
    for c in cnts:
        a=cv2.contourArea(c)
        if a<800: continue
        ap=cv2.approxPolyDP(c,0.03*cv2.arcLength(c,True),True)
        if len(ap)==4 and cv2.isContourConvex(ap) and a>ba:
            ba=a; best=ap.reshape(4,2).astype(np.float32)
    if best is None: return None,0.0
    best[:,1]+=y0
    # субпиксельное уточнение углов
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    cv2.cornerSubPix(gray,best,(7,7),(-1,-1),(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,30,0.01))
    # упорядочить TL,TR,BR,BL
    s=best.sum(1); d=np.diff(best,axis=1).ravel()
    order=np.array([best[np.argmin(s)],best[np.argmin(d)],best[np.argmax(s)],best[np.argmax(d)]])
    return order, 0.95

def _orient(p,q): return np.degrees(np.arctan2(q[1]-p[1], q[0]-p[0]))

def refine_line(img, seed, pad=26, ang_tol=22):
    """Снап линии-seed к ближайшему Hough-ребру той же ориентации в ROI. Fallback — seed."""
    p,q=np.array(seed[0],float),np.array(seed[1],float)
    x0,y0=int(min(p[0],q[0])-pad),int(min(p[1],q[1])-pad)
    x1,y1=int(max(p[0],q[0])+pad),int(max(p[1],q[1])+pad)
    H,W=img.shape[:2]; x0,y0=max(0,x0),max(0,y0); x1,y1=min(W,x1),min(H,y1)
    if x1-x0<8 or y1-y0<8: return seed,False,0.3
    roi=img[y0:y1,x0:x1]; g=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(g,40,120)
    seg=cv2.HoughLinesP(edges,1,np.pi/180,threshold=30,minLineLength=max(15,int(0.5*np.hypot(*(q-p)))),maxLineGap=12)
    if seg is None: return seed,False,0.3
    seed_ang=_orient(p,q); seed_mid=(p+q)/2
    best=None;bestscore=1e9
    for l in seg.reshape(-1,4):
        a=np.array(l[:2],float)+[x0,y0]; b=np.array(l[2:],float)+[x0,y0]
        ang=_orient(a,b)
        dang=abs(((ang-seed_ang+90)%180)-90)
        if dang>ang_tol: continue
        mid=(a+b)/2; dist=np.hypot(*(mid-seed_mid))
        score=dist - 0.15*np.hypot(*(b-a))         # ближе к seed и длиннее — лучше
        if score<bestscore: bestscore=score; best=(a,b)
    if best is None: return seed,False,0.35
    return [best[0].tolist(),best[1].tolist()], True, 0.9

def refine_vertical(img, x, y_top, y_bot, search=18):
    """Уточнить x вертикального ребра рамы окна по Hough в узкой полосе."""
    H,W=img.shape[:2]; x=int(x)
    x0,x1=max(0,x-search),min(W,x+search); y0,y1=max(0,int(y_top)),min(H,int(y_bot))
    if x1-x0<4 or y1-y0<12: return x,False
    g=cv2.cvtColor(img[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(g,40,120)
    seg=cv2.HoughLinesP(edges,1,np.pi/180,25,minLineLength=int(0.5*(y1-y0)),maxLineGap=10)
    if seg is None: return x,False
    best=None;bd=1e9
    for l in seg.reshape(-1,4):
        if abs(l[0]-l[2])>6: continue                # почти вертикаль
        xm=(l[0]+l[2])/2+x0; dd=abs(xm-x)
        if dd<bd: bd=dd; best=xm
    return (best,True) if best is not None else (x,False)
