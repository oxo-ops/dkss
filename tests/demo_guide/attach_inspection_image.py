"""Only run after real-DOM DPR3 capture; preparation in CI checkout, not deployment."""
import os,shutil,struct
from pathlib import Path
repo=Path(os.environ['PRODUCT_REPO']);source=Path(os.environ['ARTIFACTS'])/'inspection-detail-open-3x.png'
b=source.read_bytes();assert b[:8]==b'\x89PNG\r\n\x1a\n';w,h=struct.unpack('>II',b[16:24]);assert w>=900
shutil.copyfile(source,repo/'static/guide/inspection-detail-open.png')
p=repo/'static/css/first_use_guide.css';s=p.read_text();s+='\n/* Native DPR3 modal crop: no CSS offset/downsampled full-screen image. */\n.first-guide-after-picture{width:min(260px,100%);aspect-ratio:auto;overflow:visible}\n.first-guide-after-picture img{position:static;width:100%;max-width:100%;height:auto;left:auto;top:auto}\n';p.write_text(s)
p=repo/'templates/partials/first_use_guide.html';s=p.read_text().replace("filename='guide/inspection-detail-open.png')", "filename='guide/inspection-detail-open.png', v='20261118-native-3x')");s=s.replace('20261118-detail-after-preview-1','20261118-native-detail-3x').replace('20261118-ai-detail-guide-1','20261118-native-detail-3x');p.write_text(s)
