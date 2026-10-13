const $ = (s) => document.querySelector(s);
const app = { articles: [], topics: [], topic: "all", query: "", type: "all", sort: "relevance", view: "digest", marked: new Set(JSON.parse(localStorage.getItem("digest-marked") || "[]")), votes: JSON.parse(localStorage.getItem("digest-votes") || "{}"), hosted: false, connectionError: "", lastRefresh: null, refresh: {} };
const escapeHtml = (value="") => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const datePretty = (s) => { if (!s) return "日期未知"; const d = new Date(s.length===4 ? `${s}-01-01` : s); return Number.isNaN(+d) ? s : new Intl.DateTimeFormat("zh-CN",{year:"numeric",month:"short",day:"numeric",timeZone:"Asia/Shanghai"}).format(d); };
const shortTime = (s) => { if(!s)return "待同步";const d=new Date(s);return Number.isNaN(+d)?"已同步":new Intl.DateTimeFormat("zh-CN",{hour:"2-digit",minute:"2-digit",timeZone:"Asia/Shanghai"}).format(d); };

function bootDate(){ const now=new Date(); $('#today-date').textContent=new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'long',timeZone:'Asia/Shanghai'}).format(now); }
function renderTopics(){
  $('#side-topics').innerHTML=app.topics.map(t=>`<button class="side-topic ${app.topic===t.id?'selected':''}" data-topic="${escapeHtml(t.id)}"><i class="topic-dot"></i>${escapeHtml(t.label)}</button>`).join('');
  $('#topic-pills').innerHTML=`<button class="topic-pill ${app.topic==='all'?'active':''}" data-topic="all">全部方向</button>`+app.topics.map(t=>`<button class="topic-pill ${app.topic===t.id?'active':''}" data-topic="${escapeHtml(t.id)}">${escapeHtml(t.label)}</button>`).join('');
}
function paperType(a){ if((a.review_status||'').includes('预印本')) return 'preprint'; if((a.review_status||'').includes('已发表')) return 'published'; return 'unknown'; }
function filtered(){
  let list=app.articles.filter(a=>app.topic==='all'||a.topic_ids?.includes(app.topic));
  if(app.query){const q=app.query.toLowerCase();list=list.filter(a=>[a.title,a.abstract,a.authors,a.doi,a.arxiv_id,a.venue].join(' ').toLowerCase().includes(q));}
  if(app.type!=='all')list=list.filter(a=>paperType(a)===app.type);
  if(app.view==='saved')list=list.filter(a=>app.marked.has(a.id));
  list.sort((a,b)=>app.sort==='newest'?String(b.published).localeCompare(String(a.published)):b.rank_score-a.rank_score||String(b.published).localeCompare(String(a.published)));
  return list;
}
function card(a){
  const typ=paperType(a), typeLabel=typ==='preprint'?'预印本':typ==='published'?'已发表':'状态未知';
  const topicLabels=(a.topic_ids||[]).map(id=>app.topics.find(t=>t.id===id)?.label).filter(Boolean).slice(0,2);
  const source=(a.sources||[a.source]).join(' · ');
  const identifier=a.doi?`DOI ${escapeHtml(a.doi)}`:a.arxiv_id?`arXiv:${escapeHtml(a.arxiv_id)}`:a.id?`ID ${escapeHtml(a.id)}`:'';
  const paperUrl=a.url||'#';
  return `<article class="paper-card"><div class="paper-top"><div class="paper-labels"><span class="tag ${typ}">${typeLabel}</span><span class="tag topic">${escapeHtml(a.review_status||'评审状态未知')}</span>${topicLabels.map(x=>`<span class="tag topic">${escapeHtml(x)}</span>`).join('')}</div><span class="score"><i></i>${Math.round(a.rank_score)} 相关度</span></div><h3 class="paper-title"><a href="${escapeHtml(paperUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(a.title)}</a></h3><p class="paper-authors">${escapeHtml(a.authors||'作者信息暂缺')}</p>${a.abstract?`<p class="paper-abstract">${escapeHtml(a.abstract.length>510?a.abstract.slice(0,510)+'…':a.abstract)}</p>`:''}<div class="paper-reason">✳ ${escapeHtml(a.reason||'主题相关候选')}</div><div class="paper-foot"><div class="paper-meta"><span>${escapeHtml(datePretty(a.published))}</span>${a.venue?`<span class="venue">${escapeHtml(a.venue)}</span>`:''}<span>${escapeHtml(source)}</span>${identifier?`<span>${identifier}</span>`:''}</div><div class="paper-actions"><button class="paper-action ${a.vote===1?'on':''}" data-vote="1" data-id="${escapeHtml(a.id)}" title="提高相似研究排序">↑ 有关</button><button class="paper-action bad ${a.vote===-1?'on':''}" data-vote="-1" data-id="${escapeHtml(a.id)}" title="降低相似研究排序">↓ 无关</button><button class="paper-action ${app.marked.has(a.id)?'on':''}" data-mark="${escapeHtml(a.id)}" title="标记阅读">${app.marked.has(a.id)?'★ 已标记':'☆ 标记'}</button><a class="paper-action open" href="${escapeHtml(a.oa_url||paperUrl)}" target="_blank" rel="noopener noreferrer">${a.oa_url?'开放版本 ↗':'来源 ↗'}</a></div></div></article>`;
}
function render(){
  renderTopics();const list=filtered();
  $('#paper-list').innerHTML=list.map(card).join('');$('#empty-state').hidden=list.length>0||app.refresh.running;
  $('#results-total').textContent=list.length;$('#nav-count').textContent=app.articles.length;$('#saved-count').textContent=app.marked.size;
  $('#summary-total').textContent=app.articles.length;$('#summary-preprints').textContent=app.articles.filter(a=>paperType(a)==='preprint').length;$('#summary-published').textContent=app.articles.filter(a=>paperType(a)==='published').length;
  $('#summary-updated').textContent=shortTime(app.lastRefresh);const providers=(app.refresh.sources&&Object.keys(app.refresh.sources).length)?Object.keys(app.refresh.sources).join(' · '):'OpenAlex · Crossref · arXiv';$('#summary-sources').textContent=providers;
  $('#refresh-banner').hidden=!app.refresh.running;$('#refresh-button').classList.toggle('loading',!!app.refresh.running);$('#refresh-button').disabled=!!app.refresh.running;
  $('#deployment-label').textContent=app.hosted?'Netlify 在线版':'本地运行';$('#deployment-note').innerHTML=app.hosted?'每日自动检索并发布<br>可搜索与筛选简报':'每天更新一次<br>本机服务运行时自动检索';$('#refresh-button').innerHTML=app.hosted?'<span class="refresh-symbol">↻</span> 重新载入':'<span class="refresh-symbol">↻</span> 立即更新';$('#refresh-button').disabled=!!app.refresh.running;
  $('#settings-mode-title').textContent=app.hosted?'Netlify 在线简报':'本地服务说明';$('#settings-mode-copy').textContent=app.hosted?'论文由 GitHub Actions 每日检索并提交到网站数据文件，再由 Netlify 自动发布。搜索、筛选、阅读标记和相关性反馈可在此浏览器使用；反馈保存在此浏览器。':'自动更新需要这台电脑上的知研服务保持运行。简报和相关性反馈保存在本机；阅读标记保存在当前浏览器。';
  $('#footer-title').textContent=app.hosted?'知研 · Netlify 在线科研文献简报':'知研 · 本地科研文献简报';$('#footer-note').textContent=app.hosted?'开放元数据 · GitHub Actions 每日更新 · 可追溯来源':'开放元数据 · 可追溯来源 · 服务运行时每日更新';
  const errorText=app.connectionError||(app.refresh.error?`部分数据源暂时未能响应：${app.refresh.error}。已成功获取的来源仍可浏览。`:'');$('#error-banner').hidden=!errorText;$('#error-banner').textContent=errorText;
  $('.nav-item[data-view="digest"]').classList.toggle('active',app.view==='digest');$('.nav-item[data-view="saved"]').classList.toggle('active',app.view==='saved');
}
async function load(){try{const r=await fetch(app.hosted?'/digest.json':'/api/digest',{cache:app.hosted?'no-cache':'no-store'});if(!r.ok)throw new Error('无法连接简报');const data=await r.json();app.connectionError=data.pending_first_run?'每日任务已配置，等待首次检索完成。':'';app.articles=data.articles||[];app.articles.forEach(a=>{if(Object.hasOwn(app.votes,a.id))a.vote=app.votes[a.id];a.rank_score=Math.max(0,Math.min(100,a.relevance+(a.vote===1?12:a.vote===-1?-40:0)));});app.topics=data.topics||[];app.lastRefresh=data.last_refresh||data.generated_at;app.refresh=data.refresh||{};window._sources=data.configured_sources||[];render();if(app.refresh.finished&&app.refresh.finished!==app._lastFinished){app._lastFinished=app.refresh.finished;app.lastRefresh=data.last_refresh||app.refresh.finished;render();}}catch(e){app.connectionError=app.hosted?'在线简报数据尚未发布。请等待 GitHub Actions 首次每日检索成功后刷新页面。':'暂时无法连接本地简报服务。请在项目目录启动服务后刷新页面。';render();}}
async function refresh(){if(app.hosted){await load();return;}try{await fetch('/api/refresh',{method:'POST'});setTimeout(load,500);setTimeout(load,1800);setTimeout(load,5000);}catch(e){}}
async function vote(id,v){const a=app.articles.find(x=>x.id===id);if(!a)return;const next=a.vote===v?0:v;a.vote=next;a.rank_score=Math.max(0,Math.min(100,a.relevance+(next===1?12:next===-1?-40:0)));if(next)app.votes[id]=next;else delete app.votes[id];localStorage.setItem('digest-votes',JSON.stringify(app.votes));render();if(!app.hosted)try{await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,vote:next})});}catch(e){}}
function updateSaved(id){if(app.marked.has(id))app.marked.delete(id);else app.marked.add(id);localStorage.setItem('digest-marked',JSON.stringify([...app.marked]));render();}
function openSettings(){const dlg=$('#settings-dialog');const enabled=window._sources||['OpenAlex','Crossref','arXiv'];const descriptions={'OpenAlex':'开放学术索引 · 作品、摘要与开放获取信息','Crossref':'DOI 注册元数据 · 期刊与出版记录','arXiv':'预印本仓库 · 计算机、数学、物理等','Semantic Scholar':'学术图谱 · 需配置 API 密钥后启用'};const all=['OpenAlex','Crossref','arXiv','Semantic Scholar'];$('#source-list').innerHTML=all.map((n,i)=>{let on=enabled.includes(n);return `<div class="source-row"><span class="source-logo">${['O','C','a','S'][i]}</span><div><strong>${n}</strong><small>${descriptions[n]}</small></div><span class="source-state ${!on?'optional':''}">${on?'已启用':i===3?'可选':'已配置'}</span></div>`}).join('');if(!dlg.open)dlg.showModal();}

document.addEventListener('click',e=>{const t=e.target.closest('[data-topic]');if(t){app.topic=t.dataset.topic;render();return;}const v=e.target.closest('[data-view]');if(v){app.view=v.dataset.view;render();return;}const voteBtn=e.target.closest('[data-vote]');if(voteBtn){vote(voteBtn.dataset.id,Number(voteBtn.dataset.vote));return;}const mark=e.target.closest('[data-mark]');if(mark){updateSaved(mark.dataset.mark);return;}});
$('#refresh-button').addEventListener('click',refresh);$('#sources-button').addEventListener('click',openSettings);$('#search-input').addEventListener('input',e=>{app.query=e.target.value.trim();render();});$('#sort-select').addEventListener('change',e=>{app.sort=e.target.value;render();});$('#type-select').addEventListener('change',e=>{app.type=e.target.value;render();});
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('#search-input').focus();}});
async function init(){bootDate();app.hosted=!['localhost','127.0.0.1'].includes(location.hostname);await load();if(!app.hosted&&!app.articles.length&&!app.refresh.running)refresh();if(app.hosted)setInterval(load,5*60*1000);else setInterval(load,3500);render();}
init();
