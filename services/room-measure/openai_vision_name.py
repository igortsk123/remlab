"""OpenAI-vision именование КРУПНЫХ объектов: маленькие кропы батчем → точное имя+класс.
Чинит промахи Grounding DINO (дверь↔шкаф, увлажнитель↔обогреватель, стол↔радиатор).
Дёшево: кропы ужимаются до ~220px, один вызов на все крупные объекты комнаты."""
import os, json, base64, urllib.request, cv2, numpy as np
MODEL="gpt-4o-mini"   # vision, дёшево
# допустимые классы = канон таксономии (чтобы kind() работал)
CLASSES=("chair desk table sofa bed mattress wardrobe shelf fan heater radiator humidifier purifier "
         "monitor tv laptop keyboard cup bottle box books speaker router bag pillow "
         "door window mirror picture curtain plant lamp rug other").split()

def _crop_dataurl(img,box,pad=0.06,mx=220):
    H,W=img.shape[:2]; x1,y1,x2,y2=box
    px=int((x2-x1)*pad); py=int((y2-y1)*pad)
    a=max(0,x1-px);b=max(0,y1-py);c=min(W,x2+px);d=min(H,y2+py)
    cr=img[b:d,a:c]
    if cr.size==0: cr=img[y1:y2,x1:x2]
    h,w=cr.shape[:2]; s=mx/max(h,w,1)
    if s<1: cr=cv2.resize(cr,(max(1,int(w*s)),max(1,int(h*s))))
    ok,buf=cv2.imencode(".jpg",cr,[cv2.IMWRITE_JPEG_QUALITY,80])
    return "data:image/jpeg;base64,"+base64.b64encode(buf).decode()

def name_large(img, boxes):
    """boxes: list[[x1,y1,x2,y2]] → list[{"ru":str,"cls":str}] той же длины."""
    if not boxes: return []
    key=os.environ["OPENAI_API_KEY"]
    sys=("Ты называешь предмет мебели/интерьера на кропе комнаты. Для КАЖДОГО изображения по порядку верни "
         "короткое русское существительное (им.падеж, ниж.регистр) и класс СТРОГО из списка. "
         f"Классы: {' '.join(CLASSES)}. Если непонятно — cls='other'. "
         'Ответ строго JSON: {"items":[{"ru":"дверь","cls":"door"}, ...]} ровно по числу картинок и в том же порядке.')
    content=[{"type":"text","text":f"{len(boxes)} изображений по порядку:"}]
    for bx in boxes: content.append({"type":"image_url","image_url":{"url":_crop_dataurl(img,bx)}})
    body=json.dumps({"model":MODEL,"temperature":0,"response_format":{"type":"json_object"},
        "messages":[{"role":"system","content":sys},{"role":"user","content":content}]}).encode()
    req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=body,
        headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"})
    r=json.loads(urllib.request.urlopen(req,timeout=90).read())
    items=json.loads(r["choices"][0]["message"]["content"]).get("items",[])
    out=[]
    for i in range(len(boxes)):
        it=items[i] if i<len(items) else {}
        cls=it.get("cls","other"); cls=cls if cls in CLASSES else "other"
        out.append({"ru":it.get("ru","?"),"cls":cls})
    return out
