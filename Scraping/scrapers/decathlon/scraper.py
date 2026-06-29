import asyncio, os, re, sys, json
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
import aiohttp, pandas as pd
from bs4 import BeautifulSoup

BASE="https://www.decathlon.eg"
SITEMAP="https://www.decathlon.eg/sitemap-en-1.xml"
OUT="output"
TIMEOUT=45
CAIRO=timezone(timedelta(hours=2),"Africa/Cairo")

COLUMNS=["title","name","product_current_price","product_old_price","product_discount","product_url","product_image_url","product_seller","product_availability","product_category","product_subcategory","product_unit","product_weight","scraping_time","timestamp_timezone","product_brand","product_ram","product_storage"]

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}",flush=True)

def parse_price(t):
    if not t: return ""
    t=re.sub(r'[^\d.,]','',t).replace(',','').strip()
    if t:
        try: return round(float(t))
        except: pass
    return ""

CATEGORY_MAP = {
    "water-sports":"sports > water-sports","swimming":"sports > water-sports > swimming",
    "surfing":"sports > water-sports > surfing","snorkeling":"sports > water-sports > snorkeling",
    "stand-up-paddle":"sports > water-sports > stand-up-paddle","fitness":"sports > fitness",
    "bodybuilding":"sports > fitness > bodybuilding","yoga":"sports > fitness > yoga",
    "boxing":"sports > martial-arts > boxing","running":"sports > running",
    "racket-sports":"sports > racket-sports","tennis":"sports > racket-sports > tennis",
    "padel":"sports > racket-sports > padel","badminton":"sports > racket-sports > badminton",
    "ping-pong":"sports > racket-sports > ping-pong","squash":"sports > racket-sports > squash",
    "outdoor":"sports > outdoor","hiking":"sports > outdoor > hiking",
    "camping":"sports > outdoor > camping","fishing":"sports > outdoor > fishing",
    "horse-riding":"sports > outdoor > horse-riding","team-sports":"sports > team-sports",
    "football":"sports > team-sports > football","basketball":"sports > team-sports > basketball",
    "volleyball":"sports > team-sports > volleyball","urban-sports":"sports > urban-sports",
    "cycling":"sports > urban-sports > cycling","scooters":"sports > urban-sports > scooters",
    "rollerblades":"sports > urban-sports > rollerblading","skateboards":"sports > urban-sports > skateboarding",
    "men":"apparel > men","women":"apparel > women","kids":"apparel > kids",
    "babies":"apparel > kids > babies","accessories":"accessories",
    "bags":"accessories > bags","towels":"accessories > towels","electronics":"accessories > electronics",
    "nutrition":"nutrition","supplements":"nutrition > supplements","sales":"sale",
    "bikes":"sports > cycling","shoes":"apparel > shoes","footwear":"apparel > shoes",
    "t-shirts":"apparel > tops","tops":"apparel > tops","bottoms":"apparel > bottoms",
    "jackets":"apparel > jackets","pants":"apparel > bottoms","shorts":"apparel > bottoms",
    "swim":"sports > water-sports","underwear":"apparel > underwear",
    "base-layer":"apparel > base-layers","golf":"sports > golf","dance":"sports > fitness > dance",
    "gymnastics":"sports > fitness > gymnastics","skateboarding":"sports > urban-sports",
    "kiting":"sports > water-sports > kiting","diving":"sports > water-sports > diving",
    "bodyboard":"sports > water-sports > bodyboarding","beach":"sports > water-sports > beach-sports",
    "trekking":"sports > outdoor > hiking","tents":"sports > outdoor > camping",
    "sleeping":"sports > outdoor > camping","clothing":"apparel > clothing",
    "hoodies":"apparel > clothing > hoodies","sweaters":"apparel > clothing > sweaters",
    "leggings":"apparel > bottoms > leggings","tights":"apparel > bottoms > tights",
    "padel-rackets":"sports > racket-sports > padel","winter-wear":"apparel > jackets",
    "sport-accessories":"accessories",
}

KNOWN=["DOMYOS","KALENJI","KIPRUN","KIPSTA","ARTENGO","NABAIJI","QUECHUA","TRIBORD","ITIWIT","OLAÏAN","SUBEA","CORENGTH","KUIKMA","GEOLOGIC","INOVIK","OXELO","PUNCH","SOLOGNAC","CAPERLAN","OPTIMUM NUTRITION","MUSCLE ADD","EVA PHARMA","RED REX","LMTLS","FOUGANZA","BTWIN","FORCLAZ","TARMAK","ROCKRIDER","RIVERSIDE","TRIBAN","VAN RYSEL","ELOPS","INESIS","PERFLY","PONGORI","WEDZE","SIMOND","EVADICT","NEWFEEL","GEONAUTE","NYAMBA","NUTREX","ORGANIC NATION","ADVANCED NUTRITION","ADVANCED SPORTS NUTRITION","KIMJALY","LARMASAR SUMMIT","LIBRA SPORTSWEAR","MAGMA SPORTSWEAR","OUTSHOCK","OWN SNACKS","SANDEVER","SOPLUS","STAREVER","WATKO","COPA TEAMWEAR","BRUZ"]
def brand(t):
    tu=t.upper()
    for b in KNOWN:
        if b in tu: return b.title()
    return "Decathlon"

async def fetch(sem,ss,url):
    async with sem:
        try:
            async with ss.get(url,ssl=False) as r:
                if r.status==200: return await r.text()
        except: return None

async def scrape_one(url,t,sem,ss):
    html=await fetch(sem,ss,url)
    if not html: return None
    s=BeautifulSoup(html,"lxml")
    h1=s.find("h1")
    title=h1.get_text(strip=True) if h1 else ""
    if not title: return None
    cp=""
    pe=s.select_one('span.price_amount')
    if pe:
        pp=parse_price(pe.get_text(strip=True))
        if pp: cp=pp
    if not cp:
        for sel in ['[class*="current-price"]','[itemprop="price"]','[data-price]']:
            e=s.select_one(sel)
            if e:
                pp=parse_price(e.get_text(strip=True))
                if pp: cp=pp; break
    if not cp:
        for m in re.finditer(r'EGP\s*([\d,]+(?:\.\d{2})?)',s.get_text()):
            pp=parse_price(m.group(1))
            if pp and pp>0: cp=pp; break
    op=""
    oe=s.select_one('span.price_barred-amount')
    if oe:
        pp=parse_price(oe.get_text(strip=True))
        if pp and pp>0 and (not cp or pp>cp): op=pp
    if not op:
        for e in s.select('[class*="old-price"],[class*="previous-price"],del,s'):
            pp=parse_price(e.get_text(strip=True))
            if pp and pp>0 and (not cp or pp>cp): op=pp; break
    disc=round(((op-cp)/op)*100,2) if op and cp and op>cp else ""
    img=""
    e=s.select_one('meta[property="og:image"]')
    if e:
        src=e.get("content","")
        if src and not src.startswith("data:"): img=urljoin(BASE,src) if src.startswith("/") else src
    if not img:
        for img2 in s.select('img[src*="mediadecathlon"]'):
            src=img2.get("src","")
            if src: img=urljoin(BASE,src) if src.startswith("/") else src; break
    seller=""
    be=s.select_one('p.product-info_brand')
    if be: seller=be.get_text(strip=True)
    avail="in_stock"
    for sel in ['[class*="availability"]','[class*="stock"]']:
        e=s.select_one(sel)
        if e:
            a=e.get_text(strip=True).lower()
            if "out of" in a: avail="out_of_stock"; break
    name=title.split(" - ")[0] if " - " in title else title
    brand_name=brand(seller) if seller else brand(title)
    cat=""
    subcat=""
    bc=s.select('[class*="breadcrumb"] a')
    bct=[]
    for a in bc:
        at=a.get_text(strip=True).lower().replace("-"," ")
        if at!="home": bct.append(at)
    bcstr=" > ".join(bct).replace("-"," ")
    # Sort keys by length descending so more specific keys match first
    sorted_keys=sorted(CATEGORY_MAP.keys(),key=lambda x:-len(x))
    for key in sorted_keys:
        norm_key=key.replace("-"," ")
        if norm_key in bcstr:
            value=CATEGORY_MAP[key]
            parts=value.split(" > ")
            cat=" > ".join(parts[:-1]) if len(parts)>=2 else parts[0]
            subcat=parts[-1]
            break
    if not cat:
        path=urlparse(url).path.lower().replace("-"," ")
        for key in sorted_keys:
            norm_key=key.replace("-"," ")
            if norm_key in path:
                value=CATEGORY_MAP[key]
                parts=value.split(" > ")
                cat=" > ".join(parts[:-1]) if len(parts)>=2 else parts[0]
                subcat=parts[-1]
                break
    if not cat: cat="sports > general"; subcat="general"
    return {"title":title,"name":name,"product_current_price":cp or "","product_old_price":op or "","product_discount":disc if disc!="" else "","product_url":url,"product_image_url":img,"product_seller":seller if seller else "","product_availability":avail,"product_category":cat,"product_subcategory":subcat,"product_unit":"","product_weight":"","scraping_time":t,"timestamp_timezone":"Africa/Cairo","product_brand":brand_name,"product_ram":"","product_storage":""}

async def run():
    os.makedirs(OUT,exist_ok=True)
    t=datetime.now(CAIRO).strftime("%Y-%m-%d %H:%M:%S")
    raw=os.path.join(OUT,"decathlon_raw_products.csv")
    sem=asyncio.Semaphore(20)
    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Accept":"text/html"}

    done_urls=set()
    all_prods=[]
    if os.path.exists(raw):
        df=pd.read_csv(raw)
        done_urls=set(df['product_url'].dropna().tolist())
        all_prods=df.to_dict('records')
        log(f"Resumed: {len(all_prods)} existing")

    # Get sitemap URLs
    import requests as req_lib
    log("Fetching sitemap...")
    try:
        resp=req_lib.get(SITEMAP,headers={"User-Agent":"Mozilla/5.0"},timeout=30)
        xml=resp.text
    except Exception as ex:
        log(f"Failed to fetch sitemap: {ex}")
        return
    urls=set()
    for m in re.finditer(r'<loc>(https?://www\.decathlon\.eg/en/p/[^<]+)</loc>',xml):
        urls.add(m.group(1).split('?')[0])
    log(f"Total: {len(urls)} URLs, {len(done_urls)} done, {len(urls)-len(done_urls)} remaining")

    todo=sorted(u for u in urls if u not in done_urls)
    if not todo:
        log("All done, building final output...")
    else:
        log(f"Scraping {len(todo)} remaining...")
        async with aiohttp.ClientSession(headers=headers,timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as ss:
            batch=200
            for i in range(0,len(todo),batch):
                batch_urls=todo[i:i+batch]
                tasks=[scrape_one(u,t,sem,ss) for u in batch_urls]
                results=await asyncio.gather(*tasks)
                for r in results:
                    if r: all_prods.append(r)
                pd.DataFrame(all_prods,columns=COLUMNS).to_csv(raw,index=False,encoding="utf-8-sig")
                log(f"  {min(i+batch,len(todo))}/{len(todo)} - {len(all_prods)} total")

    # Build final
    log(f"Building final: {len(all_prods)} products...")
    df=pd.DataFrame(all_prods,columns=COLUMNS)
    df=df[df['title'].notna()&(df['title']!='')&(df['product_url'].notna())]
    df['product_current_price']=pd.to_numeric(df['product_current_price'],errors='coerce').fillna(0).astype(int)
    df['product_old_price']=pd.to_numeric(df['product_old_price'],errors='coerce')
    df.loc[df['product_old_price']<=df['product_current_price'],'product_old_price']=None
    df['product_discount']=df.apply(lambda r: round(((r['product_old_price']-r['product_current_price'])/r['product_old_price'])*100,2) if pd.notna(r['product_old_price']) and r['product_old_price']>r['product_current_price'] else "",axis=1)
    df['product_old_price']=df['product_old_price'].fillna("")
    df['timestamp_timezone']="Africa/Cairo"
    df=df.drop_duplicates(subset=['product_url'])

    csvf=os.path.join(OUT,"decathlon_products_clean.csv")
    jsnf=os.path.join(OUT,"decathlon_products_clean.json")
    zipf=os.path.join(OUT,"decathlon_products.zip")

    df[COLUMNS].to_csv(csvf,index=False,encoding="utf-8-sig")
    df[COLUMNS].to_json(jsnf,orient="records",force_ascii=False,indent=2)

    import zipfile
    with zipfile.ZipFile(zipf,"w",zipfile.ZIP_DEFLATED) as z:
        z.write(csvf,arcname="decathlon_products_clean.csv")
        z.write(jsnf,arcname="decathlon_products_clean.json")

    log(f"\n Results:")
    log(f"  Rows: {len(df)}")
    log(f"  With price: {(df['product_current_price']>0).sum()}")
    log(f"  Brands: {df['product_brand'].nunique()}")
    log(f"  Columns: {len(df.columns)}")
    log(f"  Files: {csvf}, {jsnf}, {zipf}")
    log(" Done!")

if __name__=="__main__":
    asyncio.run(run())
