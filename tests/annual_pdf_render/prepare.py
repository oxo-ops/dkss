from pathlib import Path
import base64,hashlib
from jinja2 import Template
root=Path('.')
# Entirely invented compatibility fixture: no user PDF bytes or business data.
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
c=canvas.Canvas('annual-source.pdf',pagesize=(595,842))
c.setFont('HeiseiKakuGo-W5',20)
c.drawString(50,760,'日本語表示の技術検証')
c.setFont('HeiseiKakuGo-W5',14)
c.drawString(50,715,'これは新規作成した架空の試験文章です。')
c.drawString(50,680,'漢字・ひらがな・カタカナ 12 ABC')
c.save()
body=Template(Path('templates/vehicle_document_pdf_viewer.html').read_text()).render(pdf_source_url='/annual-source.pdf',pdf_filename='annual-source.pdf',pdf_record_key='synthetic-annual')
Path('annual-qa.html').write_text('<!doctype html><meta charset="utf-8"><style>body{margin:12px;font-family:sans-serif}.invoice-pdf-scroll{height:900px;overflow:auto}.invoice-pdf-stage{position:relative}.invoice-pdf-page{position:relative;margin:8px auto}canvas{display:block}</style>'+body+'<script type="module">import{InvoicePdfViewer}from \'/static/js/maintenance_invoice_pdf_viewer.mjs\';window.viewer=new InvoicePdfViewer(document.querySelector(\'.invoice-pdf-viewer\'));await viewer.ready;window.ready=true;</script>',encoding='utf-8')
