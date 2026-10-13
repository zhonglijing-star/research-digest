#!/usr/bin/env python3
"""A small local-first research digest server. Python standard library only."""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import random
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
DATA = ROOT / "work" / "digest.sqlite3"
PORT = int(os.environ.get("DIGEST_PORT", "8787"))
USER_AGENT = "ResearchLiteratureDigest/0.1 (local research tool)"
CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
TODAY = lambda: dt.datetime.now(CHINA_TZ).date().isoformat()
TOPICS = [
    {"id": "governance", "label": "长期记忆治理", "query": "AI agent long-term memory governance privacy control", "terms": ["memory governance", "memory privacy", "memory control", "memory lifecycle", "forgetting policy", "user control"]},
    {"id": "memory", "label": "智能体长期记忆", "query": "agent long-term memory", "terms": ["agent memory", "long-term memory", "memory management", "memory retrieval", "continual learning"]},
    {"id": "personalization", "label": "用户建模与个性化", "query": "user modeling personalized AI agents", "terms": ["user modeling", "user model", "personalization", "personalisation", "preference learning", "individual user"]},
    {"id": "research", "label": "自动科研智能体", "query": "autonomous research agents scientific discovery", "terms": ["research agent", "scientific discovery", "automated research", "AI scientist", "literature review"]},
    {"id": "productivity", "label": "生产力增强", "query": "AI agents productivity human collaboration", "terms": ["AI productivity", "AI-enabled productivity", "human-AI collaboration", "personal assistant", "task automation", "AI workflow"]},
]

def connect():
    DATA.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS articles (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, abstract TEXT, authors TEXT,
        published TEXT, venue TEXT, doi TEXT, arxiv_id TEXT, kind TEXT,
        review_status TEXT, source TEXT NOT NULL, sources TEXT NOT NULL,
        url TEXT NOT NULL, oa_url TEXT, topic_ids TEXT NOT NULL,
        relevance REAL NOT NULL, reason TEXT, fetched_at TEXT NOT NULL, digest_day TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS feedback(article_id TEXT PRIMARY KEY, vote INTEGER NOT NULL, updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS cache(cache_key TEXT PRIMARY KEY, body TEXT NOT NULL, expires REAL NOT NULL);
    """)
    return db

def cache_key(url):
    # Cache identifiers must not persist API keys or a contact email in SQLite.
    parts=urllib.parse.urlsplit(url)
    query=[(k,v) for k,v in urllib.parse.parse_qsl(parts.query,keep_blank_values=True) if k.lower() not in ("api_key","mailto")]
    clean_url=urllib.parse.urlunsplit((parts.scheme,parts.netloc,parts.path,urllib.parse.urlencode(query),""))
    return hashlib.sha256(clean_url.encode("utf-8")).hexdigest()

def cache_get(key):
    key=cache_key(key)
    with connect() as db:
        row = db.execute("SELECT body FROM cache WHERE cache_key=? AND expires>?", (key, time.time())).fetchone()
    return json.loads(row[0]) if row else None

def cache_put(key, body, ttl=3600):
    key=cache_key(key)
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, json.dumps(body, ensure_ascii=False), time.time()+ttl))

_host_times={}; _host_lock=threading.Lock()
def polite_wait(url):
    host=urllib.parse.urlparse(url).netloc
    if host=="api.crossref.org":
        # Crossref's current list-query limits are 1 request/s in the public pool
        # and 3 requests/s in the polite pool (when mailto is supplied).
        minimum=0.4 if os.environ.get("CROSSREF_MAILTO") else 1.1
    elif host=="api.semanticscholar.org":
        minimum=1.05
    else:
        minimum=0.12 if host=="api.openalex.org" else 0.0
    with _host_lock:
        wait=minimum-(time.monotonic()-_host_times.get(host,0))
        if wait>0: time.sleep(wait)
        _host_times[host]=time.monotonic()

def request_json(url, headers=None, ttl=3600):
    cached = cache_get(url)
    if cached is not None: return cached
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    for attempt in range(4):
        try:
            polite_wait(url)
            with urllib.request.urlopen(req, timeout=25) as res:
                raw = res.read()
                result = json.loads(raw.decode("utf-8"))
                cache_put(url, result, ttl)
                return result
        except urllib.error.HTTPError as e:
            if e.code == 429 or 500 <= e.code < 600:
                retry = e.headers.get("Retry-After")
                try: delay=float(retry)
                except (TypeError,ValueError): delay=2 ** attempt + random.random()
                time.sleep(min(delay, 30))
                continue
            raise RuntimeError(f"HTTP {e.code} from {urllib.parse.urlparse(url).netloc}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == 3: raise RuntimeError(f"Request failed: {type(e).__name__}")
            time.sleep(min(2 ** attempt + random.random(), 15))
    raise RuntimeError("Request failed after retries")

def request_xml(url):
    # arXiv asks clients to leave three seconds between sequential API calls.
    with _arxiv_lock:
        wait = 3 - (time.monotonic() - _arxiv_last[0])
        if wait > 0: time.sleep(wait)
        _arxiv_last[0] = time.monotonic()
    cached = cache_get(url)
    if cached is not None: return cached
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=35) as res:
                body = res.read().decode("utf-8")
                cache_put(url, body, 4*3600)
                return body
        except urllib.error.HTTPError as e:
            if e.code == 429 or 500 <= e.code < 600:
                time.sleep(min(2 ** attempt + random.random(), 30)); continue
            raise RuntimeError(f"HTTP {e.code} from arXiv")
        except Exception as e:
            if attempt == 3: raise RuntimeError(f"arXiv request failed: {type(e).__name__}")
            time.sleep(min(2 ** attempt + random.random(), 15))

def clean(s):
    text=html.unescape(str(s or ""))
    text=re.sub(r"<[^>]*>"," ",text)
    return re.sub(r"\s+", " ", text).strip()

def abstract_from_inverted(inv):
    if not inv: return ""
    words = [""] * (max((max(pos) for pos in inv.values() if pos), default=-1) + 1)
    for word, places in inv.items():
        for pos in places:
            if 0 <= pos < len(words): words[pos] = word
    return clean(" ".join(words))

def relevance(title, abstract, topic):
    text = (title + " " + abstract).lower()
    matched = [term for term in topic["terms"] if term.lower() in text]
    title_hits = sum(1 for term in matched if term.lower() in title.lower())
    score = min(99, 34 + len(matched)*12 + title_hits*12) if matched else 0
    title_terms=[term for term in matched if term.lower() in title.lower()]
    reason = (("标题涉及"+"、".join(title_terms[:3])) if title_terms else ("摘要提及"+"、".join(matched[:3]))) if matched else ""
    return score, reason, matched

def norm_article(source, title, abstract, url, published="", doi="", arxiv_id="", venue="", authors=None, kind="", review_status="未知", oa_url="", topic=None, source_id=""):
    title, abstract = clean(title), clean(abstract)
    if not title: return None
    score, reason, matched = relevance(title, abstract, topic)
    if not matched: return None
    key = ("doi:" + doi.lower().replace("https://doi.org/", "").strip(" .")) if doi else (("arxiv:"+arxiv_id.lower()) if arxiv_id else source+":"+(source_id or re.sub(r"\W+", "-", title.lower())[:90]))
    return {"id": key, "title": title, "abstract": abstract, "authors": clean(", ".join(authors or [])), "published": published[:10], "venue": clean(venue), "doi": doi, "arxiv_id": arxiv_id, "kind": kind or "论文", "review_status": review_status, "source": source, "sources": [source], "url": url, "oa_url": oa_url, "topic_ids": [topic["id"]], "relevance": score, "reason": reason, "_matched": matched}

def openalex(topic):
    params = {"search": topic["query"], "filter": "from_publication_date:2024-01-01", "sort": "publication_date:desc", "per_page": 25, "select": "id,doi,title,publication_date,type,authorships,abstract_inverted_index,primary_location,open_access,biblio"}
    headers={}
    if os.environ.get("OPENALEX_API_KEY"): headers["Authorization"]="Bearer "+os.environ["OPENALEX_API_KEY"]
    out=[]
    for page in range(1,3):
      params["page"]=page
      data=request_json("https://api.openalex.org/works?"+urllib.parse.urlencode(params),headers=headers)
      batch=data.get("results", [])
      for w in batch:
        venue=(w.get("primary_location") or {}).get("source") or {}
        venue_name=venue.get("display_name") or ""
        typ=w.get("type") or "work"
        status="已发表；评审状态未核实" if typ in ("article", "journal-article", "review", "proceedings-article") else "评审状态未知"
        doi=(w.get("doi") or "").replace("https://doi.org/", "")
        oa=(w.get("open_access") or {}).get("oa_url") or ""
        url=oa or w.get("id") or ("https://doi.org/"+doi if doi else "")
        item=norm_article("OpenAlex",w.get("title"),abstract_from_inverted(w.get("abstract_inverted_index")),url,
                          published=w.get("publication_date") or "",doi=doi,venue=venue_name,
                          authors=[(a.get("author") or {}).get("display_name","") for a in w.get("authorships",[])[:6]],
                          kind=typ,review_status=status,oa_url=oa,topic=topic,source_id=w.get("id"))
        if item:
            item["review_status"] = status
            if not oa: item["url"] = "https://doi.org/"+doi if doi else w.get("id") or ""
            item["oa_url"] = oa
            out.append(item)
      if len(batch)<params["per_page"]: break
    return out

def crossref(topic):
    params={"query.bibliographic":topic["query"],"filter":"from-pub-date:2024-01-01","rows":25,"sort":"published","order":"desc","select":"DOI,title,author,abstract,published,type,container-title,URL,link,license","offset":0}
    mail=os.environ.get("CROSSREF_MAILTO")
    if mail: params["mailto"] = mail
    out=[]
    for page in range(2):
      params["offset"]=page*params["rows"]
      data=request_json("https://api.crossref.org/works?"+urllib.parse.urlencode(params))
      batch=data.get("message",{}).get("items",[])
      for w in batch:
        doi=w.get("DOI","")
        date=w.get("published",{}).get("date-parts",[[""]])[0]
        date="-".join(str(x).zfill(2) if i else str(x) for i,x in enumerate(date))
        title=(w.get("title") or [""])[0]
        typ=w.get("type", "")
        venue=(w.get("container-title") or [""])[0]
        # Crossref deposits metadata; a journal-article type alone does not certify peer review.
        status="预印本；评审状态未核实" if typ in ("posted-content","preprint") else ("已发表；评审状态未核实" if typ in ("journal-article","proceedings-article") else "评审状态未知")
        # Only surface a direct Crossref content URL when the deposited license
        # explicitly names a Creative Commons reuse license. Otherwise keep the
        # DOI/publisher record link and let its owner control access.
        license_urls=[str(x.get("URL","")).lower() for x in w.get("license",[])]
        openly_licensed=any("creativecommons.org/licenses/" in x for x in license_urls)
        oa=""
        for link in w.get("link",[]) if openly_licensed else []:
            if link.get("content-type","").lower()=="application/pdf" and link.get("intended-application","").lower() in ("text-mining","similarity-checking"):
                continue
            if link.get("content-type","").lower() in ("application/pdf","text/html"):
                oa=link.get("URL",""); break
        item=norm_article("Crossref",title,w.get("abstract", ""),"https://doi.org/"+doi if doi else w.get("URL", ""),date,doi,venue=venue,authors=[a.get("given","")+" "+a.get("family","") for a in w.get("author",[])[:6]],kind=typ,review_status=status,oa_url=oa,topic=topic)
        if item: out.append(item)
      if len(batch)<params["rows"]: break
    return out

_arxiv_lock=threading.Lock(); _arxiv_last=[0.0]
def arxiv(topic):
    query='all:"'+topic["query"]+'"'
    params={"search_query":query,"start":0,"max_results":30,"sortBy":"submittedDate","sortOrder":"descending"}
    ns={"a":"http://www.w3.org/2005/Atom"}
    out=[]
    for page in range(2):
      params["start"]=page*params["max_results"]
      xml=request_xml("https://export.arxiv.org/api/query?"+urllib.parse.urlencode(params))
      root=ET.fromstring(xml); batch=root.findall("a:entry",ns)
      for e in batch:
        url=e.findtext("a:id",default="",namespaces=ns).replace("http://", "https://", 1)
        arid=re.sub(r"v\d+$", "", url.rsplit("/",1)[-1])
        title=clean(e.findtext("a:title",default="",namespaces=ns)); abstract=clean(e.findtext("a:summary",default="",namespaces=ns))
        published=e.findtext("a:published",default="",namespaces=ns)
        authors=[x.findtext("a:name",default="",namespaces=ns) for x in e.findall("a:author",ns)]
        journal=clean(e.findtext("a:journal_ref",default="",namespaces=ns))
        doi=clean(e.findtext("a:doi",default="",namespaces=ns))
        item=norm_article("arXiv",title,abstract,url,published,doi,arid,journal,authors,"预印本", "预印本；未经同行评审（仓库标注）", url.replace("/abs/","/pdf/")+".pdf",topic,arid)
        if item: out.append(item)
      if len(batch)<params["max_results"]: break
    return out

def semantic_scholar(topic):
    key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if not key: return []
    params={"query":topic["query"],"limit":25,"fields":"title,abstract,authors,year,publicationDate,venue,publicationTypes,externalIds,url,openAccessPdf"}
    data=request_json("https://api.semanticscholar.org/graph/v1/paper/search?"+urllib.parse.urlencode(params),{"x-api-key":key})
    out=[]
    for p in data.get("data",[]):
        ids=p.get("externalIds") or {}; doi=ids.get("DOI",""); arid=ids.get("ArXiv","")
        types=p.get("publicationTypes") or []
        preprint="Preprint" in types or (arid and not p.get("venue"))
        status="预印本；评审状态未核实" if preprint else ("已发表；评审状态未核实" if p.get("venue") else "评审状态未知")
        oa=(p.get("openAccessPdf") or {}).get("url", "")
        item=norm_article("Semantic Scholar",p.get("title"),p.get("abstract"),p.get("url") or ("https://doi.org/"+doi if doi else "https://www.semanticscholar.org/paper/"+p.get("paperId","")),p.get("publicationDate") or str(p.get("year") or ""),doi,arid,p.get("venue") or "",[a.get("name","") for a in p.get("authors",[])[:6]],", ".join(types),status,oa,topic,p.get("paperId"))
        if item: out.append(item)
    return out

def store_articles(items):
    now=dt.datetime.now(dt.timezone.utc).isoformat(); day=TODAY()
    with connect() as db:
        for x in items:
            old=db.execute("SELECT * FROM articles WHERE id=?",(x["id"],)).fetchone()
            if old:
                merged=json.loads(old["sources"])
                if x["source"] not in merged: merged.append(x["source"])
                topics=list(dict.fromkeys(json.loads(old["topic_ids"])+x["topic_ids"]))
                # Prefer richer abstract and strongest source/relevance while retaining every provenance.
                abstract=x["abstract"] if len(x["abstract"])>len(old["abstract"] or "") else old["abstract"]
                venue=x["venue"] or old["venue"]; oa=x["oa_url"] or old["oa_url"]
                db.execute("UPDATE articles SET abstract=?,venue=?,sources=?,topic_ids=?,relevance=MAX(relevance,?),reason=CASE WHEN ? > relevance THEN ? ELSE reason END,oa_url=COALESCE(NULLIF(?,''),oa_url),kind=COALESCE(NULLIF(?,''),kind),review_status=CASE WHEN ?<>'未知' THEN ? ELSE review_status END,fetched_at=?,digest_day=? WHERE id=?",(abstract,venue,json.dumps(merged),json.dumps(topics),x["relevance"],x["relevance"],x["reason"],oa,x["kind"],x["review_status"],x["review_status"],now,day,x["id"]))
            else:
                db.execute("INSERT OR REPLACE INTO articles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(x["id"],x["title"],x["abstract"],x["authors"],x["published"],x["venue"],x["doi"],x["arxiv_id"],x["kind"],x["review_status"],x["source"],json.dumps(x["sources"]),x["url"],x["oa_url"],json.dumps(x["topic_ids"]),x["relevance"],x["reason"],now,day))

refresh_lock=threading.Lock(); refresh_state={"running":False,"started":None,"finished":None,"sources":{},"error":None}
def do_refresh():
    if not refresh_lock.acquire(blocking=False): return
    refresh_state.update(running=True,started=dt.datetime.now().astimezone().isoformat(),error=None,sources={})
    try:
        for topic in TOPICS:
            tasks=[("OpenAlex",openalex),("Crossref",crossref),("arXiv",arxiv)]
            if os.environ.get("SEMANTIC_SCHOLAR_API_KEY"): tasks.append(("Semantic Scholar",semantic_scholar))
            for name,fn in tasks:
                try:
                    got=fn(topic); store_articles(got)
                    refresh_state["sources"][name]=refresh_state["sources"].get(name,0)+len(got)
                except Exception as e:
                    refresh_state["sources"].setdefault(name,0)
                    refresh_state["error"]=(refresh_state["error"]+"；" if refresh_state["error"] else "")+f"{name}: {str(e)[:120]}"
        with connect() as db: db.execute("INSERT OR REPLACE INTO state VALUES('last_refresh',?)",(dt.datetime.now(dt.timezone.utc).isoformat(),))
    finally:
        refresh_state.update(running=False,finished=dt.datetime.now().astimezone().isoformat())
        refresh_lock.release()

def article_dict(row, vote=0):
    a=dict(row); a["sources"]=json.loads(a["sources"]); a["topic_ids"]=json.loads(a["topic_ids"]); a["vote"]=vote
    if a.get("source")=="arXiv":
        a["url"]=(a.get("url") or "").replace("http://", "https://", 1)
        a["oa_url"]=(a.get("oa_url") or "").replace("http://", "https://", 1)
    # feedback adjusts display score only; keep raw relevance for transparency
    a["rank_score"]=max(0,min(100,a["relevance"]+(12 if vote==1 else -40 if vote==-1 else 0)))
    return a

def get_digest():
    with connect() as db:
        rows=db.execute("SELECT a.*,COALESCE(f.vote,0) AS vote FROM articles a LEFT JOIN feedback f ON a.id=f.article_id ORDER BY a.published DESC LIMIT 500").fetchall()
        last=db.execute("SELECT value FROM state WHERE key='last_refresh'").fetchone()
    result=[]
    current_year=dt.datetime.now(dt.timezone.utc).year
    for r in rows:
        item=article_dict(r,r["vote"])
        item["abstract"]=clean(item.get("abstract") or "")
        year=int(item["published"][:4]) if (item.get("published") or "")[:4].isdigit() else 0
        # Daily digests focus on recent papers and omit clearly malformed publisher dates.
        if year and (year<2024 or year>current_year): continue
        topic_scores=[]
        reasons=[]
        for tid in item["topic_ids"]:
            topic=next((t for t in TOPICS if t["id"]==tid),None)
            if not topic: continue
            score,reason,matched=relevance(item["title"],item.get("abstract") or "",topic)
            if matched: topic_scores.append(score)
            if reason: reasons.append(reason)
        if not topic_scores: continue
        item["relevance"]=max(topic_scores)
        item["reason"]=" · ".join(dict.fromkeys(reasons))
        vote=item["vote"]
        item["rank_score"]=max(0,min(100,item["relevance"]+(12 if vote==1 else -40 if vote==-1 else 0)))
        result.append(item)
    result.sort(key=lambda x:(x["rank_score"],x["published"] or ""),reverse=True)
    return {"date":TODAY(),"topics":TOPICS,"articles":result,"last_refresh":last[0] if last else None,"refresh":refresh_state,"configured_sources":["OpenAlex","Crossref","arXiv"]+( ["Semantic Scholar"] if os.environ.get("SEMANTIC_SCHOLAR_API_KEY") else []),"semantic_scholar_enabled":bool(os.environ.get("SEMANTIC_SCHOLAR_API_KEY"))}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(SITE),**kwargs)
    def log_message(self,fmt,*args): pass
    def end_headers(self):
        if self.path.endswith((".js",".css",".html")) or self.path=="/":
            self.send_header("Cache-Control","no-cache, must-revalidate")
        super().end_headers()
    def send_json(self,body,status=200):
        raw=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path.startswith("/api/digest"):
            self.send_json(get_digest()); return
        super().do_GET()
    def do_POST(self):
        if self.path=="/api/refresh":
            threading.Thread(target=do_refresh,daemon=True).start(); self.send_json({"ok":True}); return
        if self.path=="/api/feedback":
            try:
                body=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
                vote=int(body.get("vote",0)); aid=str(body.get("id",""))
                if vote not in (-1,0,1) or not aid: raise ValueError()
                with connect() as db:
                    if vote==0: db.execute("DELETE FROM feedback WHERE article_id=?",(aid,))
                    else: db.execute("INSERT OR REPLACE INTO feedback VALUES(?,?,?)",(aid,vote,dt.datetime.now(dt.timezone.utc).isoformat()))
                self.send_json({"ok":True}); return
            except Exception: self.send_json({"error":"无效反馈"},400); return
        self.send_json({"error":"未找到"},404)

def scheduler():
    def run():
        # Refresh when first opened on a new day, then once per 24 hours while running.
        with connect() as db: last=db.execute("SELECT value FROM state WHERE key='last_refresh'").fetchone()
        last_day=dt.datetime.fromisoformat(last[0]).astimezone(CHINA_TZ).date().isoformat() if last else None
        if last_day != TODAY():
            threading.Thread(target=do_refresh,daemon=True).start()
        while True:
            time.sleep(24*60*60)
            threading.Thread(target=do_refresh,daemon=True).start()
    threading.Thread(target=run,daemon=True).start()

if __name__=="__main__":
    connect().close(); scheduler()
    print(f"科研文献简报已启动: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1",PORT),Handler).serve_forever()
