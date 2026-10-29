"""Two synthetic documents on the existing isolated Q12 fixture server."""
from pathlib import Path
import sys, runpy, hashlib, json
from io import BytesIO
from datetime import datetime
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'),str(ROOT/'tests')]
import benchmark_read_paths
from PIL import Image
from pypdf import PdfWriter
seed_base = benchmark_read_paths.seed

def seed(case,count):
    result = seed_base(case,count)
    m = case.m
    vehicle = m.Vehicle.query.order_by(m.Vehicle.id).first()
    # Exercise the shared header and the existing assigned-vehicle switcher.
    driver = m.Driver.query.filter_by(company_code='TEST', employee_id='admin').first()
    if driver is None:
        driver = m.Driver(company_code='TEST', employee_id='admin', name='架空 切替')
        m.db.session.add(driver)
    driver.vehicles_json = json.dumps([str(vehicle.id), '6'])
    manifest = dict(vehicle_id=vehicle.id,documents=[])
    for extension in ['jpg','pdf']:
        out = BytesIO()
        if extension == 'pdf':
            writer = PdfWriter()
            for _ in range(2): writer.add_blank_page(width=595,height=842)
            writer.write(out)
        else: Image.new('RGB',(1600,1000),'#5d86c1').save(out,format='JPEG')
        source=out.getvalue(); ident='q12-'+extension
        m.db.session.add(m.VehicleDocumentImportDraft(id=ident,batch_id='q12-batch',company_code='TEST',
            created_by_username='admin',document_type='maintenance',source_filename='q12-document.'+extension,
            source_file=source,source_sha256=hashlib.sha256(source).hexdigest(),status='completed',
            completed_at=datetime.now(),result_json=json.dumps({'records':[{'vehicle_record_id':vehicle.id}]})))
        manifest['documents'].append(dict(id=ident,extension=extension,bytes=len(source),sha256=hashlib.sha256(source).hexdigest()))
    m.db.session.commit()
    work=Path(sys.argv[sys.argv.index('--work-dir')+1]);work.mkdir(parents=True,exist_ok=True)
    (work/'documents.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return result
benchmark_read_paths.seed=seed
runpy.run_path(str(ROOT/'tools/benchmark_display_fixture.py'),run_name='__main__')
