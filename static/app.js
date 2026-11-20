const $=(s,r=document)=>r.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const TABS=[['setup','Company setup'],['profile','Intelligence profile'],['interview','AI interview'],['stack','Signal stack'],['sources','Source manager'],['feed','Intelligence feed'],['brief','Monday brief'],['internal','Internal data'],['settings','Settings & jobs']];
let CID=+localStorage.getItem('cid')||null, COMPANIES=[], TAB='setup';
async function api(p,m='GET',b){const o={method:m,headers:{}};if(b instanceof FormData)o.body=b;else if(b!==undefined){o.headers['Content-Type']='application/json';o.body=JSON.stringify(b)}
 const r=await fetch('/api'+p,o),t=await r.text();let j;try{j=JSON.parse(t)}catch{j=t}if(!r.ok)throw new Error(j.detail||t||r.statusText);return j}
function toast(m,keep){const t=$('#toast');t.textContent=m;t.style.display='block';clearTimeout(toast.h);if(!keep)toast.h=setTimeout(()=>t.style.display='none',4500)}
async function run(label,fn,btn){if(btn)btn.disabled=true;toast(label+'…',true);try{const r=await fn();toast('Done: '+label);return r}catch(e){toast('Failed: '+e.message);throw e}finally{if(btn)btn.disabled=false}}
const tag=(t,c='')=>t?`<span class="tag ${esc(c||t)}">${esc(t)}</span>`:'';
const fdate=d=>d?esc(d.slice(0,10)):'not stated';

async function boot(){
  $('#nav').innerHTML=TABS.map(([k,l])=>`<button data-k="${k}">${l}</button>`).join('');
  $('#nav').onclick=e=>{if(e.target.dataset.k)show(e.target.dataset.k)};
  const h=await api('/health');$('#llmstate').textContent=h.llm_provider?`LLM: ${h.llm_provider}`:'No LLM configured: set a free key in .env';
  await loadCompanies();show(CID?'profile':'setup');
}
async function loadCompanies(){COMPANIES=await api('/companies');const s=$('#company');s.innerHTML=COMPANIES.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')||'<option value="">No company yet</option>';
  if(!COMPANIES.find(c=>c.id===CID))CID=COMPANIES[0]?.id||null;if(CID)s.value=CID;s.onchange=()=>{CID=+s.value;localStorage.setItem('cid',CID);show(TAB)}}
function show(k){TAB=k;document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id==='v-'+k));document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.k===k));
  if(!CID&&k!=='setup'&&k!=='settings'){return show('setup')}V[k]()}
const V={};

V.setup=async()=>{const el=$('#v-setup');
 el.innerHTML=`<h2>Company setup</h2><p class="muted">Enter a company name and website. The system researches only public pages and search results, and separates verified facts from assumptions.</p>
 <div class="row"><input id="cn" class="grow" placeholder="Company name"><input id="cu" class="grow" placeholder="https://company.com"><button class="b" id="add">Add company</button></div>
 <div id="cur"></div>`;
 $('#add').onclick=async e=>{const c=await run('Creating company',()=>api('/companies','POST',{name:$('#cn').value,url:$('#cu').value}),e.target);CID=c.id;localStorage.setItem('cid',CID);await loadCompanies();V.setup()};
 if(!CID)return;const c=await api('/companies/'+CID);
 $('#cur').innerHTML=`<h3>${esc(c.name)} <span class="muted small">${esc(c.url)}</span></h3><div class="row"><button class="b" id="rs">${c.research?'Re-run':'Run'} initial research</button></div>`+researchHtml(c.research);
 $('#rs').onclick=async e=>{await run('Researching (fetches pages, may take a minute)',()=>api(`/companies/${CID}/research`,'POST'),e.target);V.setup()}};
function researchHtml(r){if(!r||!r.summary)return '<p class="muted">No research yet.</p>';
 const L=a=>(a||[]).map(x=>`<li>${esc(x)}</li>`).join('');
 return `<div class="card"><b>${esc(r.industry)}</b><p>${esc(r.summary)}</p><p class="small muted">Positioning: ${esc(r.positioning)}</p></div>
 <div class="cols"><div class="card"><h3>Verified facts (source-linked)</h3><ul>${(r.verified_facts||[]).map(f=>`<li>${esc(f.fact)} <a href="${esc(f.source_url)}" target="_blank" rel="noopener">source</a></li>`).join('')||'<li class="muted">none</li>'}</ul></div>
 <div class="card"><h3>Assumptions (not verified)</h3><ul>${(r.assumptions||[]).map(f=>`<li>${esc(f.assumption)} <span class="muted small">(${esc(f.basis)})</span></li>`).join('')||'<li class="muted">none</li>'}</ul></div></div>
 <div class="card"><h3>Segments</h3><ul>${L(r.customer_segments)}</ul><h3>Unknowns</h3><ul>${L(r.unknowns)}</ul>${(r.limitations||[]).length?`<h3>Limitations</h3><ul>${L(r.limitations)}</ul>`:''}</div>`}

V.profile=async()=>{const el=$('#v-profile');const p=await api(`/companies/${CID}/profile`);const keys=Object.keys(p).filter(k=>k!=='updated_at');
 el.innerHTML=`<h2>Company intelligence profile</h2><p class="muted">Built from research and your interview answers. Edit any field (one item per line) and save; then re-assess the Signal Stack in Settings & jobs.</p>`+
 (keys.length?keys.map(k=>`<h3>${esc(k.replace(/_/g,' '))}</h3><textarea data-k="${esc(k)}">${esc(Array.isArray(p[k])?p[k].join('\n'):p[k])}</textarea>`).join('')+`<div class="row"><button class="b" id="sv">Save profile</button><span class="muted small">Last updated ${esc(p.updated_at||'')}</span></div>`:'<p>No profile yet. Complete the interview first.</p>');
 if(keys.length)$('#sv').onclick=async e=>{const o={};el.querySelectorAll('textarea').forEach(t=>{const orig=p[t.dataset.k];o[t.dataset.k]=Array.isArray(orig)?t.value.split('\n').map(s=>s.trim()).filter(Boolean):t.value});await run('Saving profile',()=>api(`/companies/${CID}/profile`,'PUT',o),e.target)}};

V.interview=async()=>{const el=$('#v-interview');const h=await api(`/companies/${CID}/interview`);
 el.innerHTML=`<h2>AI interview</h2><p class="muted">Ten questions generated from this company's research and your previous answers. Skip anything confidential. Answered questions can be edited.</p><div id="qbox"></div><h3>Answers so far (${h.items.filter(i=>i.answer||i.skipped).length}/${h.total})</h3><div id="hist"></div>`;
 $('#hist').innerHTML=h.items.filter(i=>i.answer!==null||i.skipped).map(i=>`<div class="card"><b>${i.idx}. ${esc(i.question)}</b> ${i.followup?tag('follow-up'):''}<textarea data-q="${i.id}" ${i.skipped?'placeholder="(skipped)"':''}>${esc(i.answer||'')}</textarea><button class="b ghost sm" data-s="${i.id}">Save edit</button></div>`).join('')||'<p class="muted">Nothing yet.</p>';
 $('#hist').onclick=async e=>{const id=e.target.dataset.s;if(id){const t=$(`textarea[data-q="${id}"]`);await run('Saving answer',()=>api(`/interview/${id}/answer`,'POST',{answer:t.value}))}};
 const box=$('#qbox');
 if(h.items.filter(i=>i.answer!==null||i.skipped).length>=h.total){box.innerHTML=`<div class="card">Interview complete. <button class="b" id="bp">Build / rebuild profile from answers</button></div>`;$('#bp').onclick=async e=>{await run('Building profile',()=>api(`/companies/${CID}/profile/rebuild`,'POST'),e.target);show('profile')};return}
 box.innerHTML='<button class="b" id="nq">Get next question</button>';
 async function nextQ(){const r=await run('Generating question',()=>api(`/companies/${CID}/interview/next`,'POST'));if(r.done)return V.interview();const q=r.question;
  box.innerHTML=`<div class="card"><b>Question ${q.idx} of ${h.total}</b> ${q.followup?tag('follow-up'):''}<p>${esc(q.question)}</p><textarea id="ans"></textarea><div class="row"><button class="b" id="go">Submit answer</button><button class="b ghost" id="sk">Skip (confidential)</button></div></div>`;
  const send=async skip=>{await run('Saving',()=>api(`/interview/${q.id}/answer`,'POST',{answer:$('#ans').value,skip}));V.interview()};$('#go').onclick=()=>send(false);$('#sk').onclick=()=>send(true)}
 $('#nq').onclick=nextQ;if(h.items.some(i=>i.answer===null&&!i.skipped))nextQ()};

V.stack=async()=>{const el=$('#v-stack');const [src,comp]=await Promise.all([api(`/companies/${CID}/sources`),api(`/companies/${CID}/competitors`)]);const live=src.filter(s=>s.status!=='retired');
 el.innerHTML=`<h2>Signal stack</h2><p class="muted">Sources are proposed by the AI from the profile, then verified live (dead or blocked candidates are dropped). Approve what you want monitored.</p>
 <div class="row"><button class="b" id="bs">Build / extend signal stack</button><button class="b ghost" id="aa">Approve all proposed</button><span class="muted small">${live.length} sources · ${live.filter(s=>s.status==='approved').length} approved</span></div>`+
 ['customers','competitors','market','internal'].map(c=>`<h3>${c[0].toUpperCase()+c.slice(1)} (${live.filter(s=>s.category===c).length})</h3>`+(live.filter(s=>s.category===c).map(s=>`<div class="card"><b>${esc(s.name)}</b> ${tag(s.kind)}${tag(s.status)}<div class="muted small"><a href="${esc(s.kind==='search'?'#':s.target)}" ${s.kind==='search'?'':'target="_blank" rel="noopener"'}>${esc(s.target).slice(0,90)}</a></div><div><i>Why monitored:</i> ${esc(s.reason)}</div></div>`).join('')||'<p class="muted">None yet.</p>')).join('')+
 `<h3>Competitor profiles (${comp.length})</h3><table><tr><th>Name</th><th>Type</th><th>Site</th><th>Why it matters</th></tr>${comp.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.type)}</td><td><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.url)}</a></td><td>${esc(c.why)}</td></tr>`).join('')}</table>`;
 $('#bs').onclick=async e=>{const r=await run('Discovering and verifying sources (several minutes)',()=>api(`/companies/${CID}/stack/build`,'POST'),e.target);toast(`Added ${r.added}; ${r.rejected_candidates.length} candidates failed verification`);V.stack()};
 $('#aa').onclick=async()=>{await api(`/companies/${CID}/sources/approve_all`,'POST');V.stack()}};

V.sources=async()=>{const el=$('#v-sources');const src=await api(`/companies/${CID}/sources`);
 el.innerHTML=`<h2>Source manager</h2><div class="card"><b>Add a source</b><div class="row"><select id="nc"><option>customers</option><option>competitors</option><option>market</option></select><select id="nk"><option>rss</option><option>page</option><option>search</option><option>hn</option></select><input id="nn" class="grow" placeholder="Name"><input id="nt" class="grow" placeholder="URL or search query"></div><input id="nr" placeholder="Why monitor it?"><div class="row"><button class="b" id="na">Add (approved)</button></div></div>
 <table><tr><th>Source</th><th>Cat</th><th>Status</th><th>Health</th><th>Checked</th><th>Records</th><th>Dups</th><th></th></tr>${src.filter(s=>s.status!=='retired').map(s=>`<tr><td><b>${esc(s.name)}</b><div class="muted small">${esc(s.last_status||'')}</div></td><td>${esc(s.category)}</td><td>${tag(s.status)}</td><td>${tag(s.health)}</td><td class="small">${fdate(s.last_checked)}</td><td>${s.records}</td><td>${s.dups}</td><td>${s.status==='proposed'?`<button class="b sm" data-a="${s.id}">Approve</button> `:''}<button class="b ghost sm" data-h="${s.id}">History</button> <button class="b warn sm" data-d="${s.id}">Remove</button></td></tr>`).join('')}</table><div id="hist"></div>
 <h3>Retired sources</h3><table>${src.filter(s=>s.status==='retired').map(s=>`<tr><td>${esc(s.name)}</td><td>${esc(s.retire_reason)}</td></tr>`).join('')||'<tr><td class="muted">None</td></tr>'}</table>`;
 $('#na').onclick=async e=>{await run('Adding source',()=>api(`/companies/${CID}/sources`,'POST',{category:$('#nc').value,kind:$('#nk').value,name:$('#nn').value,target:$('#nt').value,reason:$('#nr').value}),e.target);V.sources()};
 el.onclick=async e=>{const d=e.target.dataset;if(d.a){await api(`/sources/${d.a}/approve`,'POST');V.sources()}
  if(d.d&&confirm('Remove this source?')){await api(`/sources/${d.d}`,'DELETE');V.sources()}
  if(d.h){const h=await api(`/sources/${d.h}/history`);$('#hist').innerHTML=`<h3>Crawl history</h3><table><tr><th>When</th><th>Status</th><th>Seen</th><th>New</th><th>Dup</th><th>Note</th></tr>${h.crawls.map(c=>`<tr><td>${esc(c.ts)}</td><td>${esc(c.status)}</td><td>${c.items_seen}</td><td>${c.items_new}</td><td>${c.items_dup}</td><td>${esc(c.note||'')}</td></tr>`).join('')}</table>`}}};

V.feed=async()=>{const el=$('#v-feed');const comp=await api(`/companies/${CID}/competitors`);
 el.innerHTML=`<h2>Intelligence feed</h2><div class="row"><select id="fc"><option value="">All categories</option><option>customers</option><option>competitors</option><option>market</option><option>internal</option></select>
 <select id="fe"><option value="">All competitors</option>${comp.map(c=>`<option>${esc(c.name)}</option>`).join('')}</select><select id="fi"><option value="">Any impact</option><option>opportunity</option><option>threat</option><option>neutral</option></select>
 <select id="fv"><option value="">Any verification</option><option>verified</option><option>single-source</option><option>anecdotal</option><option>unverified</option><option>internal-data</option></select>
 <input id="fs" type="date" aria-label="Since"><input id="fr" type="number" placeholder="Min rank" style="width:110px"><label class="small"><input id="fx" type="checkbox" style="width:auto"> include irrelevant</label></div>
 <div class="row"><button class="b" id="cr">Collect now</button><button class="b ghost" id="an">Analyse new records</button><span id="st" class="muted small"></span></div><div id="list"></div>`;
 const load=async()=>{const q=new URLSearchParams({category:$('#fc').value,entity:$('#fe').value,impact:$('#fi').value,verification:$('#fv').value,since:$('#fs').value,min_rank:$('#fr').value||0,include_irrelevant:$('#fx').checked});
  const [rows,st]=await Promise.all([api(`/companies/${CID}/feed?`+q),api(`/companies/${CID}/stats`)]);$('#st').textContent=`${st.records} records · ${st.analyzed} analysed · ${st.relevant} relevant · ${st.crawls} crawls`;
  $('#list').innerHTML=rows.map(r=>`<div class="card"><div>${tag(r.category)}${tag(r.impact_type)}${tag(r.verification)}${r.entity?tag(r.entity):''}<b> rank ${r.rank_score??'–'}</b></div>
  <h3 style="margin:6px 0"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a></h3>
  <div class="ev"><span class="small muted">EVIDENCE · ${esc(r.publisher)} · published ${fdate(r.published_at)} · discovered ${fdate(r.discovered_at)}</span><br>${esc(r.snippet)}${r.analysis.what_happened?`<br><span class="small">What happened: ${esc(r.analysis.what_happened)}</span>`:''}</div>
  ${r.analysis.why_it_matters?`<div class="ev i"><span class="small muted">INTERPRETATION</span><br>${esc(r.analysis.why_it_matters)} ${r.analysis.suggested_consideration?`<br><b>Consider:</b> ${esc(r.analysis.suggested_consideration)}`:''}</div>`:''}
  <div class="small muted">${esc(r.rank_explain?.why||'')} Urgency ${r.urgency??'–'}/5 · source via ${esc(r.source_name)}</div></div>`).join('')||'<p class="muted">No records match. Collect, then analyse.</p>'};
 el.querySelectorAll('select,input').forEach(i=>i.onchange=load);load();
 $('#cr').onclick=async e=>{const r=await run('Crawling approved sources',()=>api(`/companies/${CID}/crawl`,'POST'),e.target);toast(`${r.new_records} new records, ${r.errors} source errors`);load()};
 $('#an').onclick=async e=>{await run('Analysing',()=>api(`/companies/${CID}/analyze`,'POST'),e.target);load()}};

V.brief=async()=>{const el=$('#v-brief');const [bs,acts]=await Promise.all([api(`/companies/${CID}/briefs?kind=weekly`),api(`/companies/${CID}/actions`)]);
 el.innerHTML=`<h2>Monday brief</h2><div class="row"><button class="b" id="gb">Generate brief now</button><input id="wd" type="number" value="14" style="width:90px" aria-label="Window days"><span class="muted small">day window</span></div>
 <div class="row">${bs.map(b=>`<button class="b ghost sm" data-b="${b.id}">${esc(b.title)}</button>`).join('')||'<span class="muted">No briefs yet.</span>'}</div><div id="bv"></div>
 <h3>Action tracking</h3><table><tr><th>Action</th><th>Owner</th><th>Priority</th><th>Status</th></tr>${acts.map(a=>`<tr><td>${esc(a.text)}<div class="muted small">${esc(a.reason)}</div></td><td>${esc(a.owner)}</td><td>${esc(a.priority)}</td><td><select data-ac="${a.id}">${['open','in_progress','done','dismissed'].map(s=>`<option ${s===a.status?'selected':''}>${s}</option>`).join('')}</select></td></tr>`).join('')}</table>`;
 const open=async id=>{const b=await api('/briefs/'+id);$('#bv').innerHTML=`<div class="row"><a class="b ghost" style="padding:6px 10px;border-radius:6px;border:1px solid var(--sig);text-decoration:none" href="/api/briefs/${id}/export?fmt=html">Export HTML (email-ready)</a><a class="b ghost" style="padding:6px 10px;border-radius:6px;border:1px solid var(--sig);text-decoration:none" href="/api/briefs/${id}/export?fmt=md">Export Markdown</a></div><div class="brief">${b.html.replace(/^[\s\S]*?<\/style>/,'')}</div>`};
 el.onclick=e=>{if(e.target.dataset.b)open(e.target.dataset.b)};el.onchange=e=>{if(e.target.dataset.ac)api('/actions/'+e.target.dataset.ac,'PUT',{status:e.target.value})};
 $('#gb').onclick=async e=>{const r=await run('Generating brief',()=>api(`/companies/${CID}/briefs/generate?window_days=${$('#wd').value}`,'POST'),e.target);await V.brief();open(r.id)};
 if(bs[0])open(bs[0].id)};

V.internal=async()=>{const el=$('#v-internal');
 el.innerHTML=`<h2>Internal data</h2><p class="muted">Upload CRM exports, feedback, call or meeting transcripts, support logs or reports (CSV, Excel, PDF, TXT). Findings carry verbatim quotes from your files; quotes the model cannot match to the file are dropped.</p>
 <div class="row"><input type="file" id="fl" accept=".csv,.xlsx,.xls,.pdf,.txt,.md"><button class="b" id="up">Analyse file</button></div><div id="ir"></div>`;
 $('#up').onclick=async e=>{const f=$('#fl').files[0];if(!f)return toast('Choose a file first');const fd=new FormData();fd.append('file',f);const r=await run('Analysing file',()=>api(`/companies/${CID}/internal/upload`,'POST',fd),e.target);$('#ir').innerHTML=`<div class="card">Read ${r.chars_read} characters; ${r.findings_added} findings added. ${esc(r.note)} See them in the Intelligence feed (category: internal).</div>`}};

V.settings=async()=>{const el=$('#v-settings');const [s,j]=await Promise.all([api('/settings'),api('/jobs')]);
 const F=(k,l,t='text')=>`<label class="small">${l}<input data-s="${k}" type="${t}" value="${esc(s[k])}"></label>`;
 el.innerHTML=`<h2>Settings & jobs</h2><div class="cols"><div class="card"><h3>Scheduling</h3>${F('brief_day','Briefing day (mon,tue,…)')}${F('brief_time','Briefing time (HH:MM)')}${F('timezone','Time zone (IANA, e.g. Asia/Kolkata)')}${F('monitor_hours','Monitoring frequency (hours)','number')}${F('source_refresh_hours','Min hours between re-fetching one source','number')}${F('audit_day','Monthly audit day (1-28)','number')}${F('region','News region code (US, IN, GB…)')}${F('brief_window_days','Brief window (days)','number')}<div class="row"><button class="b" id="ss">Save settings</button></div>
 <p class="small muted">Next runs: ${s._next_runs.map(r=>esc(r.id+' → '+r.next_run)).join('<br>')||'scheduler not running'}</p></div>
 <div class="card"><h3>Run now${CID?'':' (select a company)'}</h3><div class="row"><button class="b" data-j="weekly">Weekly brief job</button><button class="b ghost" data-j="monitor">Monitor job</button><button class="b ghost" data-j="audit">Monthly audit</button></div>
 <h3>Context changed?</h3><textarea id="nt" placeholder="What changed in the business? e.g. 'We are now targeting students in the UK instead of India.' Edit the profile first, then re-assess."></textarea><div class="row"><button class="b" id="ra">Re-assess signal stack</button></div></div></div>
 <div id="rd"></div><h3>Audit reports</h3><div id="au"></div><h3>Job runs (failures are shown here)</h3><table><tr><th>Job</th><th>Company</th><th>Started</th><th>Status</th><th>Message</th></tr>${j.map(r=>`<tr><td>${esc(r.job)}</td><td>${esc(r.company||'')}</td><td class="small">${esc(r.started)}</td><td>${tag(r.status==='ok'?'verified':r.status==='failed'?'dead':'degraded',r.status)}</td><td class="small"><pre>${esc(r.message||'')}</pre></td></tr>`).join('')}</table>`;
 $('#ss').onclick=async e=>{const o={};el.querySelectorAll('[data-s]').forEach(i=>o[i.dataset.s]=i.type==='number'?+i.value:i.value);await run('Saving settings',()=>api('/settings','PUT',o),e.target);V.settings()};
 el.onclick=async e=>{const jb=e.target.dataset.j;if(jb&&CID){await run('Running '+jb,()=>api(`/companies/${CID}/jobs/${jb}`,'POST'),e.target).catch(()=>{});V.settings()}};
 if(CID){$('#ra').onclick=async e=>{const d=await run('Re-assessing sources',()=>api(`/companies/${CID}/reassess`,'POST',{note:$('#nt').value}),e.target);V.settings()};
  const [ch,au]=await Promise.all([api(`/companies/${CID}/stack_changes`),api(`/companies/${CID}/briefs?kind=audit`)]);
  $('#rd').innerHTML=ch.slice(0,1).map(c=>`<h3>Last signal-stack change (${esc(c.created_at)})</h3><div class="card"><i>${esc(c.note)}</i><div class="cols"><div><b>Retired (${c.diff.retired.length})</b>${c.diff.retired.map(x=>`<p class="small">${esc(x.name)}<br><span class="muted">${esc(x.reason)}</span></p>`).join('')}</div><div><b>Added (${c.diff.added.length})</b>${c.diff.added.map(x=>`<p class="small">${esc(x.name)}<br><span class="muted">${esc(x.reason)}</span></p>`).join('')}</div><div><b>Kept (${c.diff.kept.length})</b></div></div></div>`).join('');
  $('#au').innerHTML=au.map(a=>`<button class="b ghost sm" data-au="${a.id}">${esc(a.title)}</button>`).join('')||'<span class="muted">No audits yet.</span>';
  $('#au').onclick=async e=>{if(e.target.dataset.au){const b=await api('/briefs/'+e.target.dataset.au);$('#au').insertAdjacentHTML('beforeend',`<div class="brief">${b.html.replace(/^[\s\S]*?<\/style>/,'')}</div>`)}}}};
boot();
