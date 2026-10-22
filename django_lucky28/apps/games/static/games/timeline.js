(() => {
  'use strict';
  const root = document.getElementById('global-timeline');
  if (!root) return;
  const el = id => document.getElementById(`tl-${id}`);
  const make = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const read = key => {try {return JSON.parse(localStorage.getItem(key));} catch {return null;}};
  const write = (key, value) => {try {localStorage.setItem(key, JSON.stringify(value));} catch { /* Private mode */ }};
  let enabled = read('lucky28.timeline.tracks');
  if (!Array.isArray(enabled) || !enabled.every(k => typeof k === 'string')) enabled = null;
  let collapsed = read('lucky28.timeline.collapsed') || [];
  if (!Array.isArray(collapsed)) collapsed = [];
  let data, busy = false, pending = false, paused = false, page = 0, selected = null, signature = '';
  let paletteStaleMessage = '';
  let focusedGroup = null, gapFamily = 'Rows', gapMode = 'current', chartGroup = null;
  let focusedNumber = read('lucky28.palette.focus');
  if (!Number.isInteger(focusedNumber) || focusedNumber < 0 || focusedNumber > 27) focusedNumber = null;
  const pageSize = 25;
  const status = (text, error = false) => {el('status').textContent = text; el('status').classList.toggle('error', error);};
  const formatTime = value => new Date(value).toLocaleTimeString();
  const button = (text, action) => {const node = make('button', text); node.type = 'button'; node.addEventListener('click', action); return node;};

  const categories = {all:'All', S:'Small · 0–13', B:'Big · 14–27', E:'Even', O:'Odd',
    SE:'Small Even', SO:'Small Odd', BE:'Big Even', BO:'Big Odd'};
  const categoryColors = {S:'#67b9ff',B:'#ffa762',E:'#b89aff',O:'#f38ac5',SE:'#58d9d0',SO:'#d7adff',BE:'#edcc71',BO:'#a4c8ff'};
  const filterCatalog = new Map();
  const addFilter = (id,label,section,color,short=label,test=null) => filterCatalog.set(id,{id,label,section,color,short,test});
  Object.entries(categories).filter(([id])=>id!=='all').forEach(([id,label])=>addFilter(id,label,'Categories',categoryColors[id],id));
  ['Red','Orange','Magenta','Blue','Cyan / Teal','Green','Grey'].forEach((label,i)=>addFilter(`G0${i+1}`,label,'Colors',['#ef5350','#ff9800','#e754cf','#669dff','#31c8c4','#6cca7b','#aab0bb'][i]));
  for(let i=1;i<=4;i++) addFilter(`R0${i}`,`Row ${i}`,'Rows',['#91b8ff','#b6a1f2','#e8b985','#9bd8cd'][i-1],`R${i}`);
  for(let i=1;i<=7;i++) addFilter(`C0${i}`,`Column ${i}`,'Columns',`hsl(${190+i*23} 65% 72%)`,`C${i}`);
  addFilter('edges','Edges · 0–5, 22–27','Range','#e6c679','Edges');
  addFilter('middle','Middle · 6–21','Range','#abbcd3','Middle');
  addFilter('repeated','Repeated · 2+ hits','Appearances','#b8d18c','2+ hits',(_n,hits)=>hits>=2);
  addFilter('single','Single · 1 hit','Appearances','#d8b8a1','1 hit',(_n,hits)=>hits===1);
  const savedFilters = read('lucky28.palette.filters.v2');
  let activeFilters = new Set(Array.isArray(savedFilters?.ids) ? savedFilters.ids.filter(id=>filterCatalog.has(id)) : []);
  let matchMode = savedFilters?.mode === 'all' ? 'all' : 'any';
  const selections = new Map();
  let openMatches = null;
  function selectionState() {
    const stream = el('stream').value;
    if(!selections.has(stream)) selections.set(stream,{mode:'auto',numbers:new Set()});
    return selections.get(stream);
  }
  function recentNumbers() {return new Set((data?.games ?? []).slice(0,10).map(game=>game.number));}
  const selectionToolbar = make('div',undefined,'tl-selection-toolbar');
  const selectionStatus = make('p','Mode: Auto last 10'); selectionStatus.id='tl-selection-status'; selectionStatus.setAttribute('role','status');
  const selectionControls = make('div',undefined,'tl-selection-controls');
  const selectionButtons=[];
  [['Unselect last 10','unselect'],['Restore last 10','restore'],['Select absent numbers','absent'],['Clear selection','clear']].forEach(([label,action])=>{
    const control=button(label,()=>{
      const state=selectionState(), recent=recentNumbers();
      state.mode=action==='restore'?'auto':'manual';
      if(action==='restore') state.numbers=new Set(recent);
      if(action==='unselect') state.numbers=new Set([...state.numbers].filter(n=>!recent.has(n)));
      if(action==='absent') state.numbers=new Set(Array.from({length:28},(_,n)=>n).filter(n=>!recent.has(n)));
      if(action==='clear') state.numbers.clear();
      renderPalette();
    }); control.disabled=true; selectionButtons.push(control); selectionControls.append(control);
  });
  selectionToolbar.append(selectionStatus,selectionControls);
  const filterBar=make('div',undefined,'tl-palette-filters'); filterBar.setAttribute('aria-label','Filter all 28 numbers');
  const quickFilters=make('div',undefined,'tl-quick-filters');
  quickFilters.setAttribute('role','group'); quickFilters.setAttribute('aria-label','Size and parity filters');
  const filterButtons=new Map(), filterGaps=new Map(), filterStreaks=new Map(), advancedChecks=new Map();
  function toggleFilter(id) {if(activeFilters.has(id)) activeFilters.delete(id); else activeFilters.add(id); savePaletteFilters();}
  Object.entries(categories).forEach(([key,label])=>{
    const control=button(key==='all'?'All':key,()=>{if(key==='all') activeFilters.clear(); else {toggleFilter(key); return;} savePaletteFilters();});
    control.title=label; control.setAttribute('aria-label',`Filter ${label}`); control.dataset.filter=key; filterButtons.set(key,control);
    const stack=make('div',undefined,'tl-filter-stack');
    if(key!=='all') {
      stack.style.setProperty('--filter-accent',categoryColors[key]); control.style.setProperty('--filter-accent',categoryColors[key]);
      const streak=button('',()=>inspectGroup(key)); streak.className='tl-filter-streak'; streak.dataset.streak=key;
      streak.append(make('span','Streak'),make('strong','N/A'),make('small','')); streak.disabled=true; filterStreaks.set(key,streak); stack.append(streak);
    }
    stack.append(control);
    if(key!=='all') {
      const gap=button('',()=>inspectGroup(key)); gap.className='tl-filter-gap'; gap.dataset.gap=key;
      gap.append(make('span','Gap'),make('strong','N/A'),make('small','')); gap.disabled=true; filterGaps.set(key,gap); stack.append(gap);
    }
    quickFilters.append(stack);
  });
  const resetFilters=button('Clear filters',()=>{activeFilters.clear();savePaletteFilters();}); resetFilters.className='tl-clear-filters';
  const matchControls=make('div',undefined,'tl-match-controls'), matchButtons=new Map();
  matchControls.setAttribute('role','group'); matchControls.setAttribute('aria-label','Filter matching');
  [['any','Any match'],['all','All active filters']].forEach(([mode,label])=>{
    const control=button(label,()=>{matchMode=mode;savePaletteFilters();}); control.dataset.matchMode=mode; matchButtons.set(mode,control); matchControls.append(control);
  }); matchControls.append(resetFilters);
  const advanced=make('details',undefined,'tl-more-filters');
  const advancedSummary=make('summary');
  // A code-native funnel icon remains recognizable without an emoji font.
  const funnel=document.createElementNS('http://www.w3.org/2000/svg','svg'); funnel.setAttribute('viewBox','0 0 24 24'); funnel.setAttribute('aria-hidden','true');
  const funnelPath=document.createElementNS(funnel.namespaceURI,'path'); funnelPath.setAttribute('d','M3 4h18l-7 8v7l-4 2v-9z'); funnel.append(funnelPath);
  const advancedCaption=make('span','Filters (0)'); advancedSummary.append(funnel,advancedCaption); advanced.append(advancedSummary);
  const advancedBody=make('div',undefined,'tl-advanced-options');
  ['Colors','Rows','Columns','Range','Appearances'].forEach(section=>{
    const fieldset=make('fieldset'); fieldset.append(make('legend',section));
    [...filterCatalog.values()].filter(filter=>filter.section===section).forEach(filter=>{
      const label=make('label'), check=make('input'); check.type='checkbox'; check.dataset.filterId=filter.id;
      check.addEventListener('change',()=>toggleFilter(filter.id)); label.style.setProperty('--filter-accent',filter.color);
      label.append(check,make('span',filter.label)); fieldset.append(label); advancedChecks.set(filter.id,check);
    }); advancedBody.append(fieldset);
  }); advanced.append(advancedBody);
  const chips=make('div',undefined,'tl-filter-chips'); chips.setAttribute('aria-label','Active filters');
  const filterSummary=make('p','Filters apply to all 28 numbers.','tl-filter-summary'); filterSummary.id='tl-filter-summary'; filterSummary.setAttribute('role','status');
  const matchDetails=make('div',undefined,'tl-match-details'); matchDetails.id='tl-match-details'; matchDetails.hidden=true;
  matchDetails.setAttribute('role','region');matchDetails.setAttribute('aria-label','Matching filters');
  const matchDetailsText=make('p'); matchDetailsText.setAttribute('role','status');
  function closeMatchDetails() {const previous=openMatches;openMatches=null;renderMatchDetails();if(previous!==null)paletteTiles[previous].querySelector('.tl-tile-inspect').focus({preventScroll:true});}
  matchDetails.append(matchDetailsText,button('Close matches',closeMatchDetails));
  matchDetails.addEventListener('keydown',event=>{if(event.key==='Escape')closeMatchDetails();});
  filterBar.append(quickFilters,matchControls,advanced,chips,filterSummary,matchDetails);
  root.querySelector('.tl-palette-heading').after(selectionToolbar,filterBar);
  root.querySelector('.tl-palette-key').textContent='Purple = last 10 · Color strips = filter matches · Gold border = inspecting';
  function syncPaletteFilters() {
    filterButtons.forEach((control,id)=>control.setAttribute('aria-pressed',String(id==='all'?activeFilters.size===0:activeFilters.has(id))));
    advancedChecks.forEach((control,id)=>{control.checked=activeFilters.has(id);});
    matchButtons.forEach((control,mode)=>control.setAttribute('aria-pressed',String(matchMode===mode)));
    advancedCaption.textContent=`Filters (${activeFilters.size}) · color, row, column, range, repeats`;
    resetFilters.disabled=activeFilters.size===0;
    chips.replaceChildren();
    [...filterCatalog.values()].filter(filter=>activeFilters.has(filter.id)).forEach(filter=>{
      const chip=button(`${filter.label} ×`,()=>toggleFilter(filter.id)); chip.setAttribute('aria-label',`Remove ${filter.label} filter`);
      chip.style.setProperty('--filter-accent',filter.color); chips.append(chip);
    });
  }
  function savePaletteFilters() {write('lucky28.palette.filters.v2',{ids:[...activeFilters],mode:matchMode});syncPaletteFilters();renderPalette();}
  function matchingFilters(number,hits) {
    return [...filterCatalog.values()].filter(filter=>activeFilters.has(filter.id) &&
      (filter.test ? filter.test(number,hits) : data?.group_stats?.find(group=>group.key===filter.id)?.numbers.includes(number)));
  }
  function qualifies(matches) {return !activeFilters.size || (matchMode==='all'?matches.length===activeFilters.size:matches.length>0);}
  syncPaletteFilters();
  const paletteTiles=Array.from({length:28},(_,number)=>{
    const tile=make('div',undefined,'tl-number-tile'); tile.dataset.number=number;
    const selectLabel=make('label',undefined,'tl-tile-select'), checkbox=make('input'); checkbox.type='checkbox'; checkbox.disabled=true;
    checkbox.setAttribute('aria-label',`Select number ${number}`);
    checkbox.addEventListener('change',()=>{
      const state=selectionState(); state.mode='manual'; if(checkbox.checked) state.numbers.add(number);else state.numbers.delete(number);renderPalette();
    }); selectLabel.append(checkbox,make('span','Select','tl-sr-only'));
    const inspect=button('',()=>{focusedGroup=null;focusedNumber=number;write('lucky28.palette.focus',number);renderPalette();});
    inspect.className='tl-tile-inspect'; inspect.disabled=true; inspect.append(make('strong',number),make('small','—','tl-tile-hits'));
    const badge=make('span','Latest','tl-latest-badge'); badge.hidden=true;
    const recent=make('span','RECENT','tl-recent-badge'); recent.hidden=true;
    const meter=make('span',undefined,'tl-tile-meter');meter.append(make('i'));
    const strips=make('div',undefined,'tl-match-strips');
    const overlap=button('',()=>{openMatches=number;renderPalette();}); overlap.className='tl-overlap'; overlap.hidden=true;
    overlap.setAttribute('aria-controls','tl-match-details');
    overlap.addEventListener('focus',()=>{openMatches=number;renderMatchDetails();});
    overlap.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeMatchDetails();}});
    tile.append(selectLabel,inspect,recent,meter,strips,overlap,badge); el('palette').append(tile); return tile;
  });
  function renderMatchDetails() {
    if(openMatches!==null&&!matchingFilters(openMatches,data?.number_stats.find(stat=>stat.number===openMatches)?.hits??0).length)openMatches=null;
    matchDetails.hidden=openMatches===null;
    paletteTiles.forEach((tile,number)=>tile.querySelector('.tl-overlap').setAttribute('aria-expanded',String(openMatches===number)));
    if(openMatches!==null) {
      const hits=data?.number_stats.find(stat=>stat.number===openMatches)?.hits ?? 0;
      const matches=matchingFilters(openMatches,hits);
      matchDetailsText.textContent=`Number ${openMatches} · ${matches.length} matching filters: ${matches.map(filter=>filter.label).join(', ') || 'None'}. Matches count conditions, not confidence.`;
      positionMatchDetails();
    }
  }
  function positionMatchDetails() {
    if(openMatches===null||matchDetails.hidden)return;
    const anchor=paletteTiles[openMatches].querySelector('.tl-overlap').getBoundingClientRect();
    matchDetails.style.left=`${Math.max(12,Math.min(anchor.left,window.innerWidth-matchDetails.offsetWidth-12))}px`;
    const height=matchDetails.offsetHeight;
    matchDetails.style.top=`${Math.max(12,Math.min(anchor.bottom+8,window.innerHeight-height-12))}px`;
  }
  document.addEventListener('scroll',positionMatchDetails,true);window.addEventListener('resize',positionMatchDetails);

  const board=el('palette'), scroller=make('div',undefined,'tl-board-scroller'), frame=make('div',undefined,'tl-board-frame');
  scroller.tabIndex=0;scroller.setAttribute('aria-label','Number board; scroll horizontally to see all columns and metrics'); board.before(scroller);scroller.append(frame);
  const corner=make('span','Gap ↓','tl-gap-corner');
  const columnGaps=make('div',undefined,'tl-column-gaps'), rowGaps=make('div',undefined,'tl-row-gaps');
  const columnStreaks=make('div',undefined,'tl-column-streaks'), rowStreaks=make('div',undefined,'tl-row-streaks');
  const boardGaps=new Map(),boardStreaks=new Map();
  [['C',7,columnGaps,columnStreaks],['R',4,rowGaps,rowStreaks]].forEach(([prefix,count,gaps,streaks])=>{
    for(let i=1;i<=count;i++) {
      const key=`${prefix}${String(i).padStart(2,'0')}`;
      [[gaps,boardGaps,'Gap'],[streaks,boardStreaks,'Streak']].forEach(([container,map,metric])=>{
        const marker=button('',()=>inspectGroup(key));marker.className=`tl-board-metric tl-board-${metric.toLowerCase()}`;
        marker.dataset.group=key;marker.dataset.metric=metric.toLowerCase();marker.disabled=true;
        marker.append(make('span',`${prefix}${i}`),make('strong','N/A'),make('small',''));map.set(key,marker);container.append(marker);
      });
    }
  });
  const topRight=make('span','Streak ↓','tl-streak-corner');
  const bottomLeft=make('span','Streak →','tl-bottom-corner');
  frame.append(corner,columnGaps,topRight,rowGaps,board,rowStreaks,bottomLeft,columnStreaks);
  const compactSummary=make('div',undefined,'tl-compact-metrics');compactSummary.setAttribute('aria-label','All row and column gaps and streaks');
  const compactCells=new Map();
  [...boardGaps.keys()].forEach(key=>{
    const control=button('',()=>inspectGroup(key));control.dataset.summaryGroup=key;
    const label=make('strong',`${key[0]}${Number(key.slice(1))}`),gap=make('span'),streak=make('span');
    control.append(label,gap,streak);compactCells.set(key,{control,gap,streak});compactSummary.append(control);
  });
  scroller.after(make('p','Scroll the board sideways on smaller screens. All row and column metrics are also listed below.','tl-board-hint'),compactSummary);

  const analytics = make('section', undefined, 'tl-gap-analytics'); analytics.id = 'tl-gap-analytics';
  analytics.setAttribute('aria-label','Gap analytics');
  const analyticsTitle = make('h3','Gap analytics');
  const analyticsStatus = make('p','Loading group history…'); analyticsStatus.id = 'tl-gap-status'; analyticsStatus.setAttribute('role','status');
  const tabList = make('div', undefined, 'tl-gap-tabs'); tabList.setAttribute('role','tablist'); tabList.setAttribute('aria-label','Gap category');
  const gapTabs = new Map();
  const families = ['Rows','Columns','Size','Parity','Combos','Colors','Range'];
  families.forEach((family,index) => {
    const tab = button(family, () => {gapFamily = family; chartGroup = null; renderGaps();});
    tab.id = `tl-gap-tab-${family.toLowerCase()}`; tab.setAttribute('role','tab'); tab.setAttribute('aria-controls','tl-gap-panel');
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index+1)%families.length;
      if (event.key === 'ArrowLeft') next = (index+families.length-1)%families.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = families.length-1;
      if (next !== undefined) {event.preventDefault(); const target = gapTabs.get(families[next]); target.click(); target.focus();}
    });
    gapTabs.set(family,tab); tabList.append(tab);
  });
  const gapPanel = make('div'); gapPanel.id = 'tl-gap-panel'; gapPanel.setAttribute('role','tabpanel');
  const modeControls = make('div', undefined, 'tl-gap-modes'), modeButtons = new Map();
  modeControls.setAttribute('role','group'); modeControls.setAttribute('aria-label','Gap chart view');
  [['current','Current gaps'],['history','Gap history']].forEach(([mode,label]) => {
    const control = button(label, () => {gapMode = mode; renderGaps();}); control.dataset.gapMode = mode;
    modeButtons.set(mode,control); modeControls.append(control);
  });
  const groupSelectLabel = make('label','Group ', 'tl-gap-group-label');
  const groupSelect = make('select'); groupSelect.id = 'tl-gap-group';
  groupSelect.addEventListener('change', () => {chartGroup = groupSelect.value; inspectGroup(chartGroup);});
  groupSelectLabel.append(groupSelect);
  const chartTitle = make('h4'), chart = make('div', undefined, 'tl-gap-chart'); chart.id = 'tl-gap-chart';
  const chartScale = make('p', undefined, 'tl-gap-scale');
  const sortLabel=make('label','Sort ', 'tl-gap-group-label');
  const sortSelect=make('select');sortSelect.id='tl-gap-sort';
  [['desc','Largest gap first'],['asc','Smallest gap first'],['natural','Natural order']].forEach(([value,label])=>{const option=make('option',label);option.value=value;sortSelect.append(option);});
  sortSelect.value=['desc','asc','natural'].includes(read('lucky28.gaps.sort'))?read('lucky28.gaps.sort'):'desc';
  sortSelect.addEventListener('change',()=>{write('lucky28.gaps.sort',sortSelect.value);renderGaps();});sortLabel.append(sortSelect);
  const chartNote = make('p','Gaps count saved completed games, independently of palette filters. 0 = appeared in the latest result. + = not seen in available history. * = missing or unverified rounds; observed count only. Averages and maxima exclude intervals marked *.','tl-gap-note');
  gapPanel.append(modeControls,sortLabel,groupSelectLabel,chartTitle,chartScale,chart,chartNote);
  analytics.append(analyticsTitle,analyticsStatus,tabList,gapPanel);
  root.querySelector('.tl-palette-section').after(analytics);

  const metricValue=(group,metric='gap')=>{
    const value=group?.[`current_${metric}`];if(value==null)return 'N/A';
    return `${value}${group[metric==='gap'?'gap_lower_bound':'streak_lower_bound']?'+':''}${group[metric==='gap'?'current_incomplete':'streak_incomplete']?'*':''}`;
  };
  const gapValue=group=>metricValue(group);
  const groupFor=key=>data?.group_stats?.find(group=>group.key===key);
  function extrema(groups,metric) {
    const present=groups.filter(group=>group?.[`current_${metric}`]!=null);
    const maximum=present.length?Math.max(...present.map(group=>group[`current_${metric}`])):null;
    const uncertain=present.some(group=>metric==='gap'?group.gap_lower_bound||group.current_incomplete:group.streak_lower_bound||group.streak_incomplete);
    return {keys:new Set(maximum>0?present.filter(group=>group[`current_${metric}`]===maximum).map(group=>group.key):[]),
      label:uncertain?'MAX observed':'MAX',allZero:maximum===0};
  }
  const extremaNote=make('p',undefined,'tl-extrema-note');filterSummary.before(extremaNote);
  const metricHelp='Gap counts observed completed games since an appearance. Streak counts consecutive matches ending at the latest completed result. * means missing or unverified rounds; a streak stops at that boundary. + means available history limits the count. N/A means the latest completed result is unavailable. MAX observed compares known counts only.';
  compactSummary.after(make('p',metricHelp,'tl-metric-help'));
  function paintMetric(control,group,metric,comparison,populated) {
    const value=metricValue(group,metric),high=comparison.keys.has(group?.key);
    control.querySelector('strong').textContent=value;control.querySelector('small').textContent=high?comparison.label:'';
    control.classList.toggle('metric-max-gap',high&&metric==='gap');control.classList.toggle('metric-max-streak',high&&metric==='streak');
    control.classList.toggle('inspecting',populated&&focusedGroup===group?.key);control.disabled=!populated;
    control.setAttribute('aria-pressed',String(populated&&focusedGroup===group?.key));
    control.title=`${group?.label??'Group'}: ${metric} ${value}${high?`, ${comparison.label}`:''}. ${metricHelp}`;control.setAttribute('aria-label',control.title);
  }
  function inspectGroup(key) {
    const group=groupFor(key);if(!group||data.stream!==el('stream').value)return;
    focusedGroup=key;chartGroup=key;gapFamily=group.family;gapMode='history';renderPalette();
  }
  function renderGaps(clear=false) {
    const available=!clear&&data?.stream===el('stream').value&&Array.isArray(data?.group_stats),populated=available&&data.observed_games>0;
    const get=key=>available?groupFor(key):null;
    const topGroups=[...filterGaps.keys()].map(get),topGap=extrema(topGroups,'gap'),topStreak=extrema(topGroups,'streak');
    extremaNote.textContent=[topGap.allZero?'All filter gaps 0':'Highest gap = red',topStreak.allZero?'All filter streaks 0':'Highest streak = green','Tied maxima included'].join(' · ');
    filterGaps.forEach((control,key)=>paintMetric(control,get(key),'gap',topGap,populated));
    filterStreaks.forEach((control,key)=>paintMetric(control,get(key),'streak',topStreak,populated));
    const familiesMetrics={};
    ['R','C'].forEach(prefix=>{
      const groups=[...boardGaps.keys()].filter(key=>key.startsWith(prefix)).map(get);
      familiesMetrics[prefix]={gap:extrema(groups,'gap'),streak:extrema(groups,'streak')};
    });
    [[boardGaps,'gap'],[boardStreaks,'streak']].forEach(([map,metric])=>map.forEach((control,key)=>paintMetric(control,get(key),metric,familiesMetrics[key[0]][metric],populated)));
    compactCells.forEach(({control,gap,streak},key)=>{
      const group=get(key);control.disabled=!populated;
      [[gap,'gap'],[streak,'streak']].forEach(([cell,metric])=>{
        const comparison=familiesMetrics[key[0]][metric],high=comparison.keys.has(key);
        cell.textContent=`${metric==='gap'?'Gap':'Streak'} ${metricValue(group,metric)}${high?' · '+comparison.label:''}`;
        cell.className=high?`metric-max-${metric}`:'';
      });control.title=metricHelp;
    });
    corner.textContent=familiesMetrics.C.gap.allZero?'All gaps 0':'Gap ↓';
    bottomLeft.textContent=familiesMetrics.C.streak.allZero?'All streaks 0':'Streak →';
    gapTabs.forEach((tab,family)=>{const active=gapFamily===family;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;});
    gapPanel.setAttribute('aria-labelledby',`tl-gap-tab-${gapFamily.toLowerCase()}`);modeButtons.forEach((control,mode)=>control.setAttribute('aria-pressed',String(mode===gapMode)));
    analytics.classList.toggle('stale',Boolean(paletteStaleMessage));
    analyticsStatus.textContent=paletteStaleMessage?(available?'Updates unavailable · showing last loaded gap history.':paletteStaleMessage):available?`${data.observed_games} saved completed games · latest ${data.latest_game_id?'#'+data.latest_game_id:'waiting'} · checked ${formatTime(data.checked_at)}${data.latest_completed_unavailable?' · newer completed result unavailable; current streaks N/A':''}`:'Group history unavailable. Refresh to load it.';
    const groups=available?data.group_stats.filter(group=>group.family===gapFamily):[];
    if(!groups.some(group=>group.key===chartGroup))chartGroup=groups[0]?.key??null;
    if([...groupSelect.options].map(option=>option.value).join(',')!==groups.map(group=>group.key).join(','))groupSelect.replaceChildren(...groups.map(group=>{const option=make('option',group.label);option.value=group.key;return option;}));
    groupSelect.value=chartGroup??'';groupSelect.disabled=!populated;groupSelectLabel.hidden=gapMode!=='history';sortLabel.hidden=gapMode!=='current';
    const chartScroll=chart.scrollTop,focusKey=chart.contains(document.activeElement)?document.activeElement.dataset.chartId:null;
    chart.replaceChildren();chartTitle.textContent=`${gapFamily} · ${gapMode==='current'?'current absence':'gap history'}`;chartScale.textContent='';
    if(!populated){chart.append(make('p',available?'No completed results yet.':'Gap history unavailable.'));return;}
    let bars;
    if(gapMode==='current'){
      const comparison=extrema(groups,'gap');
      if(comparison.allZero)chart.append(make('p','All gaps 0'));
      const sorted=groups.map((group,index)=>({group,index}));
      if(sortSelect.value!=='natural')sorted.sort((a,b)=>{
        const x=a.group.current_gap,y=b.group.current_gap;if(x==null)return y==null?a.index-b.index:1;if(y==null)return -1;
        return (sortSelect.value==='desc'?y-x:x-y)||a.index-b.index;
      });
      bars=sorted.map(({group})=>({id:group.key,label:group.label,value:group.current_gap,text:gapValue(group),
        color:comparison.keys.has(group.key)?'#ff7e86':'#9b91b0',emphasis:comparison.keys.has(group.key)?comparison.label:'',
        action:()=>inspectGroup(group.key),title:`Members: ${group.numbers.join(', ')}. ${metricHelp}`}));
    }else{
      const group=groupFor(chartGroup);chartTitle.textContent=`${group.label} · ${group.numbers.join(', ')}`;
      bars=[{id:'ongoing',label:'Current · ongoing',value:group.current_gap,text:gapValue(group),color:group.color,ongoing:true,title:'Observed games since the last appearance. This gap is still open.'},
        ...group.history.map((item,index)=>({id:item.end.game_no,label:`${index+1}. Ended #${item.end.game_no}`,value:item.gap,text:`${item.gap}${item.incomplete?'*':''}`,color:group.color,url:item.end.url,title:`#${item.start.game_no} → #${item.end.game_no}: ${item.gap} observed misses${item.incomplete?'; missing or unverified rounds':''}`}))];
      chart.append(make('p',`Newest first · ${group.history.length} of ${group.completed_gap_count} completed gaps shown · pale = ongoing, solid = completed.`));
      if(!group.history.length)chart.append(make('p','Completed gap history needs at least two group appearances.'));
    }
    const maximum=Math.max(1,...bars.map(bar=>bar.value??0));chartScale.textContent=`Observed games absent · linear scale 0–${maximum} · every bar uses the same scale`;
    bars.forEach(bar=>{
      const row=bar.action?button('',bar.action):make(bar.url?'a':'div');if(bar.url)row.href=bar.url;
      row.className='tl-gap-bar';row.dataset.chartId=bar.id;row.title=bar.title;row.setAttribute('aria-label',`${bar.label}: ${bar.text} games absent. ${bar.emphasis??''}. ${bar.title}`);
      const track=make('span',undefined,'tl-gap-bar-track'),fill=make('i');fill.style.width=`${(bar.value??0)/maximum*100}%`;fill.style.backgroundColor=bar.color;if(bar.ongoing)fill.className='ongoing';track.append(fill);
      const count=make('span',undefined,'tl-chart-count');count.append(make('strong',bar.text),make('small',bar.emphasis??''));if(bar.emphasis)count.classList.add('metric-max-gap');
      row.append(make('span',bar.label,'tl-gap-bar-label'),count,track);chart.append(row);
    });
    if(focusKey)[...chart.querySelectorAll('[data-chart-id]')].find(node=>node.dataset.chartId===focusKey)?.focus({preventScroll:true});chart.scrollTop=chartScroll;
  }

  function renderGroupDetail(panel, group) {
    panel.append(make('div',group.label,'tl-group-hero'),make('p',`Members: ${group.numbers.join(', ')}`));
    const metrics = make('div',undefined,'tl-number-metrics');
    [[gapValue(group),'Current absence'],[metricValue(group,'streak'),'Current consecutive streak'],[group.recent_hits,`Hits / last ${Math.min(10,data.observed_games)}`],
      [group.average_gap ?? '—','Average verified gap'],[group.max_gap ?? '—','Longest verified gap']].forEach(([value,label]) => {
      const cell = make('div'); cell.append(make('strong',value),make('small',label)); metrics.append(cell);
    });
    panel.append(metrics);
    if (group.latest_appearance) {
      const last = group.latest_appearance, link = make('a',`Latest appearance: #${last.game_no} ↗`); link.href = last.url;
      panel.append(link,make('p',new Date(last.timestamp).toLocaleString()));
    } else panel.append(make('p',`Not seen in ${data.observed_games} saved completed games.`));
    panel.append(make('p',`${group.total_hits} appearances · ${group.exact_gap_count} verified completed gaps. ${metricHelp}`));
    const apply = button('Apply palette filter', () => {
      activeFilters.add(group.key);savePaletteFilters();
    }); apply.className = 'tl-group-apply';
    panel.append(apply,make('p','Adds this group to active filters across all 28 numbers. Selection and gap counts stay unchanged.'));
    const historyButton = button('View gap history ↓', () => {gapMode = 'history'; chartGroup = group.key; gapFamily = group.family; renderGaps(); analytics.scrollIntoView({behavior:'smooth',block:'start'});});
    historyButton.className = 'tl-group-apply'; panel.append(historyButton);
  }
  renderGaps();

  function paletteUnavailable(message, clear = false) {
    paletteStaleMessage=message;
    root.querySelector('.tl-palette-section').classList.add('stale');el('palette-status').textContent=message;
    el('palette').setAttribute('aria-busy','false');renderGaps(clear);
    if(clear || !data || data.stream!==el('stream').value) {
      selectionButtons.forEach(control=>{control.disabled=true;});
      selectionStatus.textContent=`Mode: ${selectionState().mode==='auto'?'Auto last 10':'Manual'} · waiting for history`;
      filterSummary.textContent='History unavailable · filter definitions are retained.';
      paletteTiles.forEach(tile=>{
        tile.querySelector('input').disabled=true;tile.querySelector('input').checked=false;tile.querySelector('.tl-tile-inspect').disabled=true;
        tile.classList.remove('present','focused','filter-match','filtered-out','number-selected');tile.style.removeProperty('--tile-fill');
        tile.querySelector('.tl-tile-hits').textContent='N/A';tile.querySelector('.tl-latest-badge').hidden=true;tile.querySelector('.tl-recent-badge').hidden=true;
        tile.querySelector('.tl-match-strips').replaceChildren();tile.querySelector('.tl-overlap').hidden=true;
        tile.querySelector('.tl-tile-meter i').style.width='0';
      });
      matchDetails.hidden=true;
      el('number-detail').replaceChildren(make('h3','History unavailable'),make('p',message));el('recent-results').replaceChildren();
    } else {renderPalette();}
  }

  function renderPalette() {
    if(!data || data.stream!==el('stream').value) return;
    renderGaps();
    const seen=new Set(), history=data.games.filter(game=>{if(seen.has(game.game_no))return false;seen.add(game.game_no);return true;});
    const recent=history.slice(0,10), counts=new Map();recent.forEach(game=>counts.set(game.number,(counts.get(game.number)??0)+1));
    const latestNumber=recent[0]?.number??null, state=selectionState();
    if(state.mode==='auto') state.numbers=new Set(counts.keys());
    selectionButtons.forEach(control=>{control.disabled=false;});
    const matchesByNumber=Array.from({length:28},(_,n)=>matchingFilters(n,counts.get(n)??0));
    const matching=matchesByNumber.map((matches,n)=>qualifies(matches)?n:null).filter(n=>n!==null);
    selectionStatus.textContent=`Mode: ${state.mode==='auto'?'Auto last 10':'Manual'} · ${state.numbers.size} selected · ${counts.size} recent distinct · ${matching.length} filter matches${paletteStaleMessage?' · last loaded data':''}`;
    filterSummary.textContent=`${paletteStaleMessage?'Last loaded · ':''}${activeFilters.size ? matching.length ? `${matching.length} of 28 numbers match ${matchMode==='all'?'all active filters':'any active filter'}` : `No numbers match ${matchMode==='all'?'all active filters':'any active filter'}` : 'All 28 numbers eligible · no active filters'}. Selection is unchanged by filters.`;
    root.querySelector('.tl-palette-section').classList.toggle('stale',Boolean(paletteStaleMessage));el('palette').setAttribute('aria-busy','false');
    el('palette-status').textContent=paletteStaleMessage || (recent.length?`Last ${recent.length} results · ${counts.size} recent distinct numbers · #${data.latest_game_id} · checked ${formatTime(data.checked_at)}`:'No completed results yet. Select numbers manually or wait for the first result.');
    paletteTiles.forEach((tile,number)=>{
      const hits=counts.get(number)??0,matches=matchesByNumber[number],qualified=qualifies(matches),inspected=focusedGroup===null && focusedNumber===number;
      const checkbox=tile.querySelector('input'),inspect=tile.querySelector('.tl-tile-inspect');
      checkbox.disabled=false;checkbox.checked=state.numbers.has(number);inspect.disabled=false;
      tile.classList.toggle('present',hits>0);tile.classList.toggle('number-selected',state.numbers.has(number));
      tile.classList.toggle('filter-match',qualified);tile.classList.toggle('filtered-out',!qualified);tile.classList.toggle('focused',inspected);
      tile.dataset.matchCount=matches.length;tile.dataset.qualified=String(qualified);inspect.setAttribute('aria-pressed',String(inspected));
      inspect.setAttribute('aria-label',`Inspect number ${number}: ${hits} hits in last ${recent.length} results${number===latestNumber?', latest result':''}`);
      tile.querySelector('.tl-tile-hits').textContent=`${hits} ${hits===1?'hit':'hits'}`;
      tile.querySelector('.tl-tile-meter i').style.width=`${recent.length?hits/recent.length*100:0}%`;
      tile.querySelector('.tl-recent-badge').hidden=hits===0;tile.querySelector('.tl-latest-badge').hidden=number!==latestNumber;
      const strips=tile.querySelector('.tl-match-strips');strips.replaceChildren();
      matches.slice(0,3).forEach(filter=>{const strip=make('span',filter.short);strip.style.setProperty('--strip-color',filter.color);strips.append(strip);});
      if(matches.length>3) strips.append(make('small',`+${matches.length-3} more`));
      if(matches.length) {
        const colors=matches.slice(0,3).map(filter=>`color-mix(in srgb, ${filter.color} ${qualified?'30':'14'}%, #201a31)`);
        tile.style.setProperty('--tile-fill',colors.length===1?colors[0]:`linear-gradient(135deg,${colors.map((color,i)=>`${color} ${i/colors.length*100}%,${color} ${(i+1)/colors.length*100}%`).join(',')})`);
      } else tile.style.removeProperty('--tile-fill');
      const overlap=tile.querySelector('.tl-overlap');overlap.hidden=matches.length===0;overlap.textContent=`×${matches.length}`;
      overlap.title=`Number ${number}: ${matches.map(filter=>filter.label).join(', ')}`;
      overlap.setAttribute('aria-label',`Show matching filters for number ${number}: ${matches.map(filter=>filter.label).join(', ')}`);
      overlap.setAttribute('aria-expanded',String(openMatches===number));
    });
    renderMatchDetails();
    const strip=el('recent-results');strip.replaceChildren();if(recent.length)strip.append(make('span','Newest →'));
    recent.forEach(game=>{const a=make('a',game.number);a.href=game.url;a.title=`Game #${game.game_no}`;strip.append(a);});
    const panel=el('number-detail');panel.replaceChildren();
    if(focusedGroup && groupFor(focusedGroup)){renderGroupDetail(panel,groupFor(focusedGroup));return;}
    if(focusedNumber===null){panel.append(make('h3','Inspect a number'),make('p','Click a number to inspect it. Use its checkbox to select it.'));return;}
    const stat=data.number_stats.find(s=>s.number===focusedNumber);
    panel.append(make('div',focusedNumber,'tl-number-hero'),make('h3',`Number ${focusedNumber}`));
    panel.append(make('p',`${stat.size} · ${stat.parity} · ${stat.color} · Row ${Math.floor(focusedNumber/7)+1}, Column ${focusedNumber%7+1}`));
    const metrics=make('div',undefined,'tl-number-metrics');
    [[counts.get(focusedNumber)??0,`Hits / last ${recent.length}`],[stat.current_gap===null?'N/A':`${stat.current_gap}${stat.gap_lower_bound?'+':''}`,'Observed games since seen'],[stat.max_gap??'N/A','Longest completed gap'],[stat.average_gap??'N/A','Average completed gap']].forEach(([value,label])=>{const cell=make('div');cell.append(make('strong',value),make('small',label));metrics.append(cell);});
    panel.append(metrics);
    if(stat.latest_appearance){const last=stat.latest_appearance,link=make('a',`Latest appearance: #${last.game_no} ↗`);link.href=last.url;panel.append(link,make('p',new Date(last.timestamp).toLocaleString()));}
    else panel.append(make('p',`Not seen in ${data.observed_games} saved completed games. The current gap is a lower bound.`));
    panel.append(make('p',`Gap statistics use ${data.observed_games} saved completed games. Missing results are not counted; averages require two appearances.`));
    const appearances=history.filter(game=>game.number===focusedNumber);panel.append(make('h3',`Appearances in latest ${history.length} (${appearances.length})`));
    if(!appearances.length)panel.append(make('p','No appearance in this timeline.'));
    const list=make('ul',undefined,'tl-number-appearances');appearances.forEach(game=>{const li=make('li'),link=make('a',`#${game.game_no} · ${formatTime(game.timestamp)}`);link.href=game.url;li.append(link);list.append(li);});panel.append(list);
  }

  function renderDetail() {
    const container = el('detail');
    container.replaceChildren();
    const game = data.games.find(g => g.game_no === selected);
    if (!game) {container.textContent = 'Select a result to see its game details and recorded alerts.'; return;}
    const link = make('a', `Game #${game.game_no} ↗`); link.href = game.url;
    container.append(link, make('span', ` · Number ${game.number} · ${new Date(game.timestamp).toLocaleString()}`));
    if (game.gap_before) container.append(make('p', 'History gap before this game. Pattern calculations stop at this boundary.'));
    const classifications = data.tracks.filter(t => t.tracker_key !== 'alerts').map(track => {
      const item = track.timeline.find(i => i.game_no === game.game_no);
      const state = item && track.legend.find(s => s.letter === item.letter);
      return state ? `${track.display_name}: ${state.label}` : null;
    }).filter(Boolean);
    container.append(make('p', classifications.join(' · ')));
    if (!enabled.includes('alerts')) {container.append(make('p', 'Enable Recorded alerts to load saved alert evidence.')); return;}
    if (!game.alerts.length) {container.append(make('p', 'No alert event recorded for this game.')); return;}
    const list = make('ul');
    game.alerts.forEach(alert => {const li = make('li'); const a = make('a', alert.title); a.href = alert.url; li.append(a, make('span', ` — ${alert.detail}`)); list.append(li);});
    container.append(list);
  }

  function render() {
    renderPalette();
    page = Math.min(page, Math.max(0, Math.ceil(data.games.length / pageSize) - 1));
    const start = page * pageSize, games = data.games.slice(start, start + pageSize);
    const scroller = el('grid'), scrollLeft = scroller.scrollLeft, scrollTop = scroller.scrollTop;
    el('range').textContent = games.length ? `Games ${start + 1}–${start + games.length} of ${data.games.length} / 150 · newest first` : 'Waiting for completed games';
    el('prev').disabled = page === 0; el('next').disabled = start + pageSize >= data.games.length;
    scroller.replaceChildren();
    if (!games.length || !data.tracks.length) scroller.append(make('div', !games.length ? 'No completed results yet. New games appear automatically.' : 'Choose tracks above to display the timeline.', 'tl-empty'));
    else {
      const table = make('table', undefined, 'tl-table');
      const head = make('thead'), header = make('tr'); header.append(make('th', 'Track / game →', 'tl-row-label'));
      games.forEach(game => {const th = make('th'); th.scope = 'col'; th.title = `Game #${game.game_no}`; th.append(make('div', `#${game.game_no.slice(-6)}`), make('div', formatTime(game.timestamp))); header.append(th);});
      head.append(header); table.append(head);
      const body = make('tbody');
      data.tracks.forEach(track => {
        const tr = make('tr'); tr.dataset.track = track.tracker_key;
        const label = make('th', undefined, 'tl-row-label'); label.scope = 'row';
        label.append(make('span', track.display_name, 'tl-name'));
        const isCollapsed = collapsed.includes(track.tracker_key);
        const toggle = button(isCollapsed ? 'Expand' : 'Collapse', () => {
          collapsed = isCollapsed ? collapsed.filter(k => k !== track.tracker_key) : [...collapsed, track.tracker_key];
          write('lucky28.timeline.collapsed', collapsed); render();
        }); toggle.setAttribute('aria-expanded', String(!isCollapsed));
        label.append(toggle, button(track.reset ? 'Restore history' : 'Reset', () => reset(track)));
        tr.append(label);
        const indexed = new Map(track.timeline.map(item => [item.game_no, item]));
        if (isCollapsed) {const td = make('td', 'Track collapsed'); td.colSpan = games.length; tr.append(td);}
        else games.forEach(game => {
          const item = indexed.get(game.game_no), td = make('td');
          if (game.gap_before) td.classList.add('tl-gap');
          if (game.game_no === selected) td.classList.add('tl-selected');
          if (item) {
            const state = track.legend.find(s => s.letter === item.letter);
            const dot = button(item.letter === 'A' ? String(game.alerts.length) : item.letter, () => {selected = game.game_no; render();});
            dot.className = 'tl-dot'; dot.style.setProperty('--dot-color', state.color);
            dot.title = `Game #${game.game_no} · Number ${game.number} · ${state.label}${game.alerts.length ? ` · ${game.alerts.length} saved alerts` : ''}`;
            dot.setAttribute('aria-label', `${track.display_name}: ${dot.title}`); td.append(dot);
          } else {td.textContent = '—'; td.title = 'Before this track’s reset. Waiting for new games.';}
          tr.append(td);
        });
        body.append(tr);
        if (!isCollapsed && track.tracker_key !== 'number') {
          const legendRow = make('tr', undefined, 'tl-legend-row'); legendRow.append(make('th', '', 'tl-row-label'));
          const td = make('td'); td.colSpan = games.length;
          const legend = make('div', undefined, 'tl-legend');
          track.legend.forEach(s => {const span = make('span'); const dot = make('i'); dot.style.background = s.color; span.append(dot, document.createTextNode(`${s.letter} ${s.label}`)); legend.append(span);});
          td.append(legend); legendRow.append(td); body.append(legendRow);
        }
      });
      table.append(body); scroller.append(table); scroller.scrollLeft = scrollLeft; scroller.scrollTop = scrollTop;
    }
    const events = el('events'); events.replaceChildren();
    data.tracks.forEach(track => track.active_events.forEach(event => {
      const node = make('div', `${track.display_name} · ${event.title}`, 'tl-event');
      node.append(make('small', event.desc)); events.append(node);
    }));
    if (!events.children.length) events.append(make('p', 'No current pattern observations for the selected tracks.'));
    renderDetail();
  }

  function settings() {
    const options = el('track-options'); options.replaceChildren();
    data.catalog.forEach(track => {
      const label = make('label'), input = make('input'); input.type = 'checkbox'; input.checked = enabled.includes(track.key);
      input.addEventListener('change', () => {
        enabled = input.checked ? [...enabled, track.key] : enabled.filter(k => k !== track.key);
        write('lucky28.timeline.tracks', enabled);
        data.tracks = data.tracks.filter(t => enabled.includes(t.tracker_key)); render(); fetchData();
      });
      label.append(input, document.createTextNode(track.title)); options.append(label);
    });
    const selectedStream = el('stream').value;
    el('stream').replaceChildren(...data.streams.map(key => {const option = make('option', key); option.value = key; return option;}));
    el('stream').value = data.streams.includes(selectedStream) ? selectedStream : 'lucky28';
  }

  async function fetchData() {
    if (busy) {pending = true; return;}
    busy = true;
    const requestedStream = el('stream').value;
    const requestedTracks = enabled === null ? null : enabled.join(',');
    try {
      const url = new URL(root.dataset.feed, location.origin); url.searchParams.set('stream', requestedStream);
      if (requestedTracks !== null) url.searchParams.set('tracks', requestedTracks);
      const response = await fetch(url, {cache: 'no-store', signal: AbortSignal.timeout(12000)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const next = await response.json();
      if (requestedStream !== el('stream').value || requestedTracks !== (enabled === null ? null : enabled.join(','))) {pending = true; return;}
      if (enabled === null) {enabled = next.catalog.map(t => t.key); write('lucky28.timeline.tracks', enabled);}
      data = next;
      paletteStaleMessage = '';
      const nextSignature = JSON.stringify([data.games, data.tracks, data.number_stats, data.group_stats, data.observed_games]);
      if (nextSignature !== signature) {render(); signature = nextSignature;}
      else renderPalette();
      settings();
      status(`${paused ? 'Paused' : 'Live · checks every 5s'} · checked ${formatTime(data.checked_at)} · latest ${data.latest_game_id ? '#' + data.latest_game_id : 'waiting'}${data.has_gaps ? ' · history gaps marked' : ''}`);
    } catch (error) {
      status(`Refresh failed — ${data ? 'showing last loaded results' : 'history unavailable'}. Retrying in 5s. (${error.message})`, true);
      paletteUnavailable(data && data.stream === el('stream').value ? 'Updates unavailable · showing the last loaded palette and details.' : 'History unavailable. Retrying automatically.');
    }
    finally {busy = false; if (pending) {pending = false; fetchData();}}
  }

  async function reset(track) {
    try {
      const token = root.querySelector('[name=csrfmiddlewaretoken]').value;
      const url = new URL(root.dataset.reset.replace('TRACK', encodeURIComponent(track.tracker_key)), location.origin);
      url.searchParams.set('stream', el('stream').value);
      const response = await fetch(url, {method: 'POST', headers: {'X-CSRFToken': decodeURIComponent(token || '')}, body: new URLSearchParams({action: track.reset ? 'restore' : 'reset'}), signal: AbortSignal.timeout(12000)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await fetchData();
    } catch (error) {status(`Could not change this track: ${error.message}`, true);}
  }
  el('refresh').addEventListener('click', fetchData);
  el('pause').addEventListener('click', () => {paused = !paused; el('pause').textContent = paused ? 'Resume' : 'Pause'; el('pause').setAttribute('aria-pressed', String(paused)); if (!paused) fetchData(); else status('Paused · automatic refresh stopped');});
  el('stream').addEventListener('change', () => {page = 0; selected = null; signature = ''; paletteUnavailable('Loading selected stream…', true); status('Loading selected stream…'); fetchData();});
  el('prev').addEventListener('click', () => {page--; render();});
  el('next').addEventListener('click', () => {page++; render();});
  document.addEventListener('visibilitychange', () => {if (!document.hidden && !paused) fetchData();});
  setInterval(() => {if (!paused && !document.hidden) fetchData();}, 5000);
  fetchData();
})();
