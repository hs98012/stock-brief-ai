import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import pytesseract
from pdf2image import convert_from_path

from .models import TextSource
from .page_layout import (native_observation, ocr_words, serialize_ocr)
from .fact_fusion import PARSER_VERSION

OCR_DPI = int(os.getenv('OCR_DPI', '300'))


@dataclass
class ExtractedPage:
    page_number: int; native_text: str | None; ocr_text: str | None; final_text: str
    text_source: TextSource; page_image_path: str | None; ocr_error: str | None
    provenance: dict = field(default_factory=dict)
    table_facts: list[dict] = field(default_factory=list)


@dataclass
class OCRPage:
    text: str
    image_path: str
    words: list[dict]


def needs_ocr(native_text: str | None, minimum=None) -> bool:
    """Legacy text-only helper: no length threshold. Production uses page observations."""
    return not (native_text or '').strip() or '\ufffd' in (native_text or '')


def ocr_page(pdf_path: Path, page_number: int, image_dir: Path, regions=None, covered=()) -> OCRPage:
    image_dir.mkdir(parents=True, exist_ok=True)
    images = convert_from_path(str(pdf_path), dpi=OCR_DPI, first_page=page_number, last_page=page_number, fmt='png', use_cropbox=True)
    if not images:
        raise RuntimeError('페이지 이미지를 생성할 수 없습니다.')
    image_path = image_dir / f'page-{page_number:04d}.png'
    images[0].save(image_path, 'PNG')
    with fitz.open(pdf_path) as document:
        rect = document[page_number-1].rect
        sx,sy = images[0].width/rect.width,images[0].height/rect.height
        from PIL import ImageDraw
        masked=images[0].copy()
        draw=ImageDraw.Draw(masked)
        for box in covered:
            rotated=fitz.Rect(box)*document[page_number-1].rotation_matrix
            draw.rectangle((rotated.x0*sx,rotated.y0*sy,rotated.x1*sx,rotated.y1*sy),fill='white')
        words=[]
        regions = regions if regions is not None else [[0,0,rect.width,rect.height]]
        # Independent raster/layout interpretations. Lower DPI may retain glyph
        # shapes lost when a low-resolution embedded image is upsampled.
        modes=[(OCR_DPI,6,masked)]
        secondary=convert_from_path(str(pdf_path),dpi=200,first_page=page_number,last_page=page_number,
            fmt='png',use_cropbox=True)[0]
        draw_secondary=ImageDraw.Draw(secondary)
        for box in covered:
            rotated=fitz.Rect(box)*document[page_number-1].rotation_matrix
            draw_secondary.rectangle((rotated.x0*secondary.width/rect.width,rotated.y0*secondary.height/rect.height,
                rotated.x1*secondary.width/rect.width,rotated.y1*secondary.height/rect.height),fill='white')
        modes.append((200,3,secondary))
        for dpi,psm,raster in modes:
            rx,ry=raster.width/rect.width,raster.height/rect.height
            for region_index,box in enumerate(regions):
                x0,y0,x1,y1=box
                crop_box=(max(0,int(x0*rx)),max(0,int(y0*ry)),min(raster.width,int(x1*rx)),min(raster.height,int(y1*ry)))
                data=pytesseract.image_to_data(raster.crop(crop_box),lang='kor+eng',
                    config=f'--psm {psm}',output_type=pytesseract.Output.DICT)
                recognized=ocr_words(data,1/rx,1/ry)
                for word in recognized:
                    a,b,c,d=word['bbox'];word['bbox']=[a+crop_box[0]/rx,b+crop_box[1]/ry,c+crop_box[0]/rx,d+crop_box[1]/ry]
                    word['line_id']=f"r{region_index}:d{dpi}:p{psm}:"+word['line_id']
                    word['region_id']=region_index
                    word['ocr_psm']=psm;word['ocr_dpi']=dpi;word['ocr_stream']=f'region:{dpi}:{psm}'
                words.extend(recognized)
        # Preserve page-layout recognition context while masking native coverage.
        # This is still OCR only of uncovered regions, with candidates kept separate.
        canvas=secondary.copy();mask=ImageDraw.Draw(canvas)
        from PIL import Image
        allowed=Image.new('RGB',canvas.size,'white')
        for x0,y0,x1,y1 in regions:
            box=(max(0,int(x0*canvas.width/rect.width)),max(0,int(y0*canvas.height/rect.height)),
                 min(canvas.width,int(x1*canvas.width/rect.width)),min(canvas.height,int(y1*canvas.height/rect.height)))
            allowed.paste(canvas.crop(box),box)
        data=pytesseract.image_to_data(allowed,lang='kor+eng',
            config='--psm 6 -c preserve_interword_spaces=1',output_type=pytesseract.Output.DICT)
        for word in ocr_words(data,rect.width/canvas.width,rect.height/canvas.height):
            cx=(word['bbox'][0]+word['bbox'][2])/2;cy=(word['bbox'][1]+word['bbox'][3])/2
            region_id=next((i for i,b in enumerate(regions) if b[0]<=cx<=b[2] and b[1]<=cy<=b[3]),None)
            if region_id is None:continue
            word.update(region_id=region_id,ocr_psm=6,ocr_dpi=200,ocr_stream='page_context:200:6')
            word['line_id']='page_context:'+word['line_id'];words.append(word)
        # A bounded second segmentation pass can confirm, never replace, a weak token.
        grouped={}
        for word in words:
            grouped.setdefault((word['text'],tuple(round(v,1) for v in word['bbox'])),[]).append(word)
        numeric=[g for g in grouped.values() if g[0]['confidence']<80 and re.search(r'\d',g[0]['text'])]
        labels=[g for g in grouped.values() if g[0]['confidence']<80 and not re.search(r'\d',g[0]['text'])
                and re.search(r'[가-힣A-Za-z]',g[0]['text'])]
        numeric.sort(key=lambda g:(not bool(re.fullmatch(r'[1-4]Q\d{2}[FEAP]?|20\d{2}[FEAP]',g[0]['text'])),-g[0]['confidence']))
        labels.sort(key=lambda g:-g[0]['confidence'])
        for group in numeric[:16]+labels[:16]:
            word=group[0]
            x0,y0,x1,y1 = word['bbox']
            sx,sy = images[0].width/rect.width,images[0].height/rect.height
            crop_box = [max(0,int(x0*sx)-8),max(0,int(y0*sy)-8),
                        min(images[0].width,int(x1*sx)+8),min(images[0].height,int(y1*sy)+8)]
            check = pytesseract.image_to_data(images[0].crop(crop_box), lang='kor+eng',
                config='--psm 7', output_type=pytesseract.Output.DICT)
            tokens = [(t.strip(),float(c)) for t,c in zip(check['text'],check['conf']) if t.strip()]
            exact = bool(tokens) and ''.join(t for t,c in tokens)==word['text'] and min(c for t,c in tokens)>=80
            word['confirmation'] = {'mode':'cropped_psm7','dpi':OCR_DPI,'text':' '.join(t for t,c in tokens),
                                    'min_confidence':min((c for t,c in tokens),default=-1), 'crop_pixels':crop_box}
            word['confirmed_exact'] = exact
            for other in group[1:]:
                other['confirmation']=word['confirmation'];other['confirmed_exact']=exact
        if document[page_number-1].rotation:
            for word in words:
                word['bbox'] = list(fitz.Rect(word['bbox']) * document[page_number-1].derotation_matrix)
    return OCRPage(serialize_ocr(words), str(image_path), words)


def extract_pdf(pdf_path: Path, image_dir: Path, *, force_ocr: bool = False) -> list[ExtractedPage]:
    from .fused_extraction import extract_page
    try:
        document=fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError('손상되었거나 읽을 수 없는 PDF입니다.') from exc
    if not document.is_pdf or document.page_count < 1:
        document.close()
        raise ValueError('유효한 PDF 문서가 아닙니다.')
    try:
        return [extract_page(page,index+1,pdf_path,image_dir,force_ocr=force_ocr)
                for index,page in enumerate(document)]
    finally:
        document.close()
