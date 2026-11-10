"""Download the public raw datasets for EnergyFlex AI.
Run: python download_public_data.py
Requires: pip install requests
No synthetic data. Validates archives and MD5 when published.
"""
from pathlib import Path
import hashlib, tarfile, zipfile, sys
import requests

OUT = Path(__file__).resolve().parent
FILES = [
    ('HEATWISE_AAU.tar.xz', 'https://zenodo.org/records/22797095/files/AAU.tar.xz?download=1', '13d33d17938006a0055d79652c982dd9'),
    ('HEATWISE_PSNC.tar.xz', 'https://zenodo.org/records/22797095/files/PSNC.tar.xz?download=1', 'e7d01101999393643f0b9bf9ce0a125f'),
    ('NLR_ESIF_power.csv.zip', 'https://data.nlr.gov/system/files/300/1757105566-esif.influx.buildingData.PUE.combined.csv.zip', None),
    ('NLR_ESIF_weather.csv.zip', 'https://data.nlr.gov/system/files/300/1757105566-esif.influx.buildingData.outside.combined.csv.zip', None),
]

def md5(path):
    h=hashlib.md5()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def download(name,url,expected):
    path=OUT/name
    if path.exists() and path.stat().st_size:
        if expected is None or md5(path)==expected:
            print(f'[SKIP] {name}: already present'); return
        print(f'[RETRY] {name}: existing checksum mismatch');path.unlink()
    print(f'[GET] {name}')
    tmp=path.with_suffix(path.suffix+'.part')
    with requests.get(url,stream=True,timeout=(20,90),headers={'User-Agent':'Mozilla/5.0 EnergyFlex-data-research/1.0'}) as r:
        r.raise_for_status()
        with open(tmp,'wb') as f:
            for piece in r.iter_content(chunk_size=1024*1024):
                if piece:f.write(piece)
    tmp.replace(path)
    if expected and md5(path)!=expected:
        path.unlink();raise ValueError(f'MD5 mismatch for {name}')
    if name.endswith('.zip'):
        with zipfile.ZipFile(path) as z:
            bad=z.testzip()
            if bad:raise ValueError(f'Corrupt entry {bad}')
            print('       Archive OK, entries:',len(z.namelist()))
    if name.endswith('.tar.xz'):
        with tarfile.open(path,'r:xz') as t:
            print('       Archive OK, entries:',len(t.getmembers()))
    print('       Saved',path.stat().st_size,'bytes')

def main():
    print('EnergyFlex public data downloader — saves original source archives')
    fails=[]
    for name,url,expected in FILES:
        try:download(name,url,expected)
        except Exception as e:print('[FAILED]',name,str(e));fails.append(name)
    if fails:
        print('\nDownload failed:',', '.join(fails));return 1
    print('\nAll source archives downloaded and checked.')
    return 0

if __name__=='__main__':sys.exit(main())
