(() => {
  'use strict';
  const root=document.getElementById('case-study');if(!root)return;
  const el=id=>document.getElementById(`cs-${id}`);
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const time=value=>value?new Date(value).toLocaleString():'Unavailable';
  const percent=value=>`${(Number(value)*100).toFixed(2)}%`;
  const modeName={prospective:'Before receipt',retrospective:'Historical review',late:'Late record'};
  const pill=mode=>{const p=node('span',modeName[mode]??mode,'cs-pill');p.dataset.mode=mode;return p;};
  let data=null,mode='prospective',selected=null,busy=false,timer=null,detailRequest=0,signature='';
  function section(title){const s=node('section',undefined,'cs-detail-section');s.append(node('h4',title));return s;}
  function list(items){const ul=node('ul');items.forEach(x=>ul.append(node('li',x)));return ul;}
  function audit(title,value){const d=node('details',undefined,'cs-audit');d.append(node('summary',title),node('pre',JSON.stringify(value,null,2)));return d;}
  function strategyCards(forecast){
    const grid=node('div',undefined,'cs-strategies');
    (forecast.strategies??[]).forEach(strategy=>{
      const card=node('article',undefined,'cs-strategy');card.append(node('h3',strategy.name),node('p',strategy.description));
      const balls=node('div',undefined,'cs-ranked');
      strategy.ranked_numbers.slice(0,5).forEach(n=>{const r=node('div',undefined,'cs-rank');r.append(node('span',n,'cs-ball'),node('small',percent(strategy.probabilities[n])));balls.append(r);});
      card.append(balls);
      const sets=node('div',undefined,'cs-top-sets');
      [1,3,5].forEach(k=>{const t=strategy.top[String(k)];sets.append(node('span',`Top ${k}: ${t.numbers.join(', ')} · estimated coverage ${percent(t.coverage)}`));});
      card.append(sets,audit('Recorded ranking reasons',strategy.reasons));grid.append(card);
    });return grid;
  }
  function renderPending(){
    const pending=data.pending??[];el('pending-count').textContent=`${pending.length} pending`;
    el('pending').replaceChildren();
    if(!pending.length){el('pending').append(node('p','No current pre-result ranking recorded. The recorder needs a live pending round; completed history is never labeled as a live forecast.','cs-empty'));return;}
    pending.forEach(record=>{const box=node('article',undefined,'cs-pending-round');box.append(node('h3',`Round #${record.round_id}`),
      node('p',`Saved ${time(record.created_at)} · ${record.history_count} earlier results · history ${record.history_quality.status}`,'cs-pending-meta'),strategyCards(record),
      node('p',record.timing_note,'cs-muted'),node('p',record.selection_source,'cs-muted'));el('pending').append(box);});
  }
  function renderPerformance(){
    el('mode-prospective').setAttribute('aria-pressed',String(mode==='prospective'));el('mode-retrospective').setAttribute('aria-pressed',String(mode==='retrospective'));
    el('performance-note').textContent=mode==='prospective'?'Only forecasts saved before local result receipt are scored here. Compare each method with the baseline on the same rounds and shortlist size. These are exploratory measurements, not proof of an advantage.':'Historical replay uses earlier saved results only. Data may contain later imports or corrections; this is not a record of predictions made at the time.';
    const body=el('performance');body.replaceChildren();const rows=(data.performance??[]).filter(r=>r.mode===mode);
    rows.forEach(r=>{const tr=node('tr');[r.label,r.top_k,r.samples,`${r.hits} / ${r.samples-r.hits}`,`${r.hit_rate.toFixed(2)}%`,`${r.baseline_rate.toFixed(2)}%`,`${r.lift_pp>0?'+':''}${r.lift_pp.toFixed(2)} pp`,r.verdict].forEach(value=>tr.append(node('td',value)));body.append(tr);});
    if(!rows.length){const tr=node('tr'),td=node('td','No scored rounds in this sample yet.');td.colSpan=8;tr.append(td);body.append(tr);}
  }
  function renderCases(){
    const search=el('case-search').value.trim(),filter=el('case-mode').value;
    const cases=(data.cases??[]).filter(c=>(filter==='all'||c.mode===filter)&&(!search||String(c.number)===search||c.round_id.includes(search)));
    el('case-count').textContent=`${cases.length} of ${(data.cases??[]).length} recent cases`;
    const container=el('cases'),position=container.scrollTop,focus=document.activeElement?.dataset.caseId;
    container.replaceChildren();
    cases.forEach(c=>{const button=node('button',undefined,'cs-case');button.type='button';button.dataset.caseId=c.id;button.setAttribute('aria-pressed',String(c.id===selected));
      const meta=node('span',undefined,'cs-case-meta');meta.append(node('strong',`#${c.round_id}`),node('time',time(c.observed_at)),pill(c.mode));
      button.append(node('span',c.number,'cs-ball'),meta);button.addEventListener('click',()=>loadDetail(c.id));container.append(button);
    });
    if(!cases.length)container.append(node('p','No matching cases.','cs-empty'));
    if(focus)container.querySelector(`[data-case-id="${CSS.escape(focus)}"]`)?.focus({preventScroll:true});container.scrollTop=position;
  }
  async function loadDetail(id){
    selected=id;renderCases();const request=++detailRequest;el('detail').setAttribute('aria-busy','true');
    try{
      const response=await fetch(`${root.dataset.detailBase}${id}/`,{cache:'no-store'});if(!response.ok)throw Error('Could not load the saved evidence.');
      const record=await response.json();if(request!==detailRequest)return;renderDetail(record);
    }catch(error){if(request===detailRequest)el('detail').replaceChildren(node('p',error.message,'cs-error'));}
    finally{if(request===detailRequest)el('detail').setAttribute('aria-busy','false');}
  }
  function renderDetail(record){
    const panel=el('detail'),e=record.explanation,g=e.groups;panel.replaceChildren();
    const heading=node('div',undefined,'cs-result-heading'),titles=node('div');titles.append(node('h3',`Result ${record.result.number} · #${record.round_id}`),pill(record.mode));
    const ball=node('span',record.result.number,'cs-ball');ball.style.borderColor=g.color_hex;heading.append(ball,titles);panel.append(heading,
      node('p',`${g.size} · ${g.parity} · ${g.combination} · ${g.color} · ${g.row} · ${g.column}`),node('p',record.eligibility_reason,'cs-muted'));
    const facts=node('div',undefined,'cs-detail-facts');
    [['Observed',time(record.result.observed_at)],['Logged',time(record.logged_at)],['Evidence revision',record.revision],['New / Repeated',e.classification.label]].forEach(([label,value])=>{const f=node('div',undefined,'cs-fact');f.append(node('small',label),node('strong',value));facts.append(f);});panel.append(facts);
    const calculation=section('Calculation evidence');calculation.append(node('p',e.calculation.expression??'Digits unavailable','cs-digits'),node('p',`${e.calculation.status}: ${e.calculation.detail}`),node('p',e.generation_cause,'cs-warning'));panel.append(calculation);
    const context=section('Observed matches · not proven causes'),gap=e.number_gap;
    context.append(node('p',e.classification.detail),node('p',`Preceding results, oldest first: ${e.classification.previous_ten.join(', ')||'Unavailable'}`),
      node('p',`Number absence before this result: ${gap.lower_bound?'at least ':''}${gap.observed_games} observed rounds${gap.interrupted?' · interrupted history':''}.`),
      list(e.observed_matches.map(m=>m.detail)),node('p','Streak changes'),list(e.broken_streaks.length?e.broken_streaks.map(s=>s.detail):['No verified streak ending recorded.']));panel.append(context);
    const outcome=section(record.mode==='prospective'?'Recorded selection outcomes':'Replayed selection outcomes');
    e.strategy_results.forEach(s=>{outcome.append(node('h4',s.name),list([1,3,5].map(k=>{const t=s.top[String(k)];return `Top ${k}: ${t.numbers.join(', ')} — ${t.hit?'Included':'Missed'} · recorded estimate ${percent(t.coverage)}`;})));});
    outcome.append(node('p',record.selection_source,'cs-muted'),audit('Full ranking and reasons',record.forecast));panel.append(outcome);
    const alerts=section('Saved alert evidence');alerts.append(list(record.prior_alerts.length?record.prior_alerts.map(a=>`${a.title}: ${a.detail} · saved ${time(a.captured_at)}`):['No earlier alert evidence recorded for this round.']));panel.append(alerts);
    const auditSection=section('Evidence log');auditSection.append(node('p',record.timing_note,'cs-muted'),list(record.events.map(x=>`${time(x.created_at)} · ${x.kind}${x.case_id?' · case '+x.case_id:''}`)),
      list(e.limitations),audit('Complete saved case',record));panel.append(auditSection);
  }
  async function refresh(){
    if(busy||document.hidden)return;busy=true;clearTimeout(timer);const stream=el('stream').value;
    try{
      const response=await fetch(`${root.dataset.api}?stream=${encodeURIComponent(stream)}`,{cache:'no-store'});if(!response.ok)throw Error(`Case study unavailable (${response.status}).`);
      const next=await response.json();if(stream!==el('stream').value)return;data=next;
      const running=data.worker.running;el('status').textContent=running?`Recorder active · checked ${time(data.checked_at)} · refreshes every 3 seconds`:`Recorder offline · ${data.worker.error||'Start case_study_worker to capture new rounds.'}`;el('status').dataset.state=running?'live':'error';
      const options=[...el('stream').options].map(o=>o.value);if(JSON.stringify(options)!==JSON.stringify(data.streams)){el('stream').replaceChildren(...data.streams.map(s=>{const o=node('option',s);o.value=s;return o;}));el('stream').value=stream;}
      el('export').href=`${root.dataset.export}?stream=${encodeURIComponent(stream)}`;
      const key=JSON.stringify([data.pending,data.performance,data.cases,data.totals]);
      if(key!==signature){signature=key;el('summary').replaceChildren(...['prospective','retrospective','late'].map(m=>{const s=node('div',undefined,'cs-stat');s.append(node('strong',data.totals[m]??0),node('span',modeName[m]));return s;}));renderPending();renderPerformance();renderCases();
        if(selected===null&&data.cases.length)loadDetail(data.cases[0].id);
      }
    }catch(error){el('status').textContent=`${error.message} Last loaded evidence remains visible.`;el('status').dataset.state='error';}
    finally{busy=false;if(!document.hidden)timer=setTimeout(refresh,3000);}
  }
  el('stream').addEventListener('change',()=>{selected=null;signature='';detailRequest++;el('detail').replaceChildren(node('p','Loading this stream…','cs-empty'));refresh();});
  el('refresh').addEventListener('click',refresh);
  ['case-search','case-mode'].forEach(id=>el(id).addEventListener(id==='case-search'?'input':'change',()=>{if(data)renderCases();}));
  ['prospective','retrospective'].forEach(m=>el(`mode-${m}`).addEventListener('click',()=>{mode=m;if(data)renderPerformance();}));
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)refresh();});
  refresh();
})();
