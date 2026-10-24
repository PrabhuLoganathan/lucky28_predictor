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
  let pollTimer, feedETag='', feedKey='';
  const pollDelay=1000;
  let focusedGroup = null, gapFamily = 'Rows', gapMode = 'current', chartGroup = null;
  let focusedNumber = read('lucky28.palette.focus');
  if (!Number.isInteger(focusedNumber) || focusedNumber < 0 || focusedNumber > 27) focusedNumber = null;
  const pageSize = 25;
  const status = (text, error = false) => {el('status').textContent = text; el('status').classList.toggle('error', error);};
  const formatTime = value => new Date(value).toLocaleTimeString();
  const button = (text, action) => {const node = make('button', text); node.type = 'button'; node.addEventListener('click', action); return node;};

  const numberModel = window.Lucky28Numbers;
  const universe = Array.from({length:28},(_,n)=>n);
  const categories = {S:'Small · 0–13',B:'Big · 14–27',E:'Even',O:'Odd',SE:'Small Even',SO:'Small Odd',BE:'Big Even',BO:'Big Odd'};
  const memberships = new Map();
  Object.keys(categories).forEach(key=>memberships.set(key,universe.filter(n=>
    (!key.includes('S') || n<14) && (!key.includes('B') || n>=14) &&
    (!key.includes('E') || n%2===0) && (!key.includes('O') || n%2===1))));
  for(let i=0;i<4;i++) memberships.set(`R0${i+1}`,universe.filter(n=>Math.floor(n/7)===i));
  for(let i=0;i<7;i++) memberships.set(`C0${i+1}`,universe.filter(n=>n%7===i));
  const selections = new Map(), groupButtons = new Map();
  let recentMembers = [], historyReady = false;
  function selectionState() {
    const stream=el('stream').value;
    if(!selections.has(stream))selections.set(stream,{mode:'auto',numbers:new Set(),target:''});
    return selections.get(stream);
  }
  function membersFor(key) {
    if(key==='recent')return recentMembers;
    if(key==='absent')return historyReady?universe.filter(n=>!recentMembers.includes(n)):[];
    return memberships.get(key)??[];
  }
  function toggleNumbers(members) {
    if(!members.length)return;
    const state=selectionState();state.mode='manual';state.numbers=numberModel.toggle(state.numbers,members);renderPalette();
  }
  function groupButton(key,label) {
    const control=button('',()=>toggleNumbers(membersFor(key)));
    control.className='tl-selection-group';control.dataset.selectionGroup=key;
    control.append(make('span',label),make('small',''));groupButtons.set(key,{control,label});return control;
  }
  const selectionToolbar=make('div',undefined,'tl-selection-toolbar');
  const selectionStatus=make('p','Mode: Auto last 10');selectionStatus.id='tl-selection-status';selectionStatus.setAttribute('role','status');
  const selectionControls=make('div',undefined,'tl-selection-controls');
  selectionControls.append(groupButton('recent','Last 10'),groupButton('absent','Absent in last 10'));
  selectionToolbar.append(selectionStatus,selectionControls);
  const filterBar=make('div',undefined,'tl-palette-filters');filterBar.setAttribute('aria-label','Category selection and metrics');
  const quickFilters=make('div',undefined,'tl-quick-filters');
  const filterGaps=new Map(),filterStreaks=new Map();
  Object.entries(categories).forEach(([key,label])=>{
    const stack=make('div',undefined,'tl-filter-stack');
    const metric=(name,map)=>{const control=button('',()=>inspectGroup(key));control.className=`tl-filter-${name.toLowerCase()}`;
      control.dataset[name.toLowerCase()]=key;control.append(make('span',name),make('strong','N/A'),make('small',''));map.set(key,control);return control;};
    const control=groupButton(key,key);control.title=label;
    stack.append(metric('Streak',filterStreaks),control,metric('Gap',filterGaps));quickFilters.append(stack);
  });
  const filterSummary=make('p','Click a group to select its members; click a fully selected group to clear it.','tl-filter-summary');filterSummary.id='tl-filter-summary';
  filterBar.append(quickFilters,filterSummary);
  root.querySelector('.tl-palette-heading').after(selectionToolbar,filterBar);
  root.querySelector('.tl-palette-key').textContent='Purple = selected · Details opens inspection';
  root.querySelector('.tl-palette-note').textContent='Recent hits describe the latest available completed results. Missing rounds are not evidence of absence.';
  const paletteTiles=universe.map(number=>{
    const tile=make('div',undefined,'tl-number-tile');tile.dataset.number=number;
    const select=button('',()=>toggleNumbers([number]));select.className='tl-tile-toggle';
    const resultTag=make('small',undefined,'tl-palette-result-tag');resultTag.hidden=true;
    select.append(make('strong',number),make('small','N/A','tl-tile-hits'),resultTag);
    const details=button('Details',()=>{focusedGroup=null;focusedNumber=number;write('lucky28.palette.focus',number);renderPalette();});
    details.className='tl-tile-details';details.setAttribute('aria-label',`Details for number ${number}`);
    const badge=make('span','Latest','tl-latest-badge');badge.hidden=true;
    tile.append(select,details,badge);el('palette').append(tile);return tile;
  });

  const probability=make('section',undefined,'tl-probability');probability.id='tl-probability';probability.setAttribute('aria-label','Selected number probability comparison');
  probability.append(make('h3','Selected number probability comparison'),make('p',numberModel.model.label));
  const targetLabel=make('label','Selection target ', 'tl-target-label'),targetSelect=make('select');targetSelect.id='tl-selection-target';
  [['','No target'],... [1,3,5,10,14].map(n=>[String(n),String(n)])].forEach(([value,label])=>{const option=make('option',label);option.value=value;targetSelect.append(option);});
  targetSelect.addEventListener('change',()=>{selectionState().target=targetSelect.value;renderProbability();});targetLabel.append(targetSelect);
  const targetStatus=make('p');targetStatus.id='tl-target-status';
  const probabilityCards=make('div',undefined,'tl-probability-cards'),probabilityText=make('p');probabilityText.id='tl-probability-status';probabilityText.setAttribute('role','status');
  const probabilityBar=make('div',undefined,'tl-probability-bar');probabilityBar.setAttribute('role','img');
  const selectedBar=make('span'),unselectedBar=make('span');probabilityBar.append(selectedBar,unselectedBar);
  const complement=make('details'),complementList=make('p');complement.append(make('summary','Show unselected numbers'),complementList);
  probability.append(targetLabel,targetStatus,probabilityCards,probabilityBar,probabilityText,complement,
    make('p',`Model ${numberModel.model.version} · Outcome coverage only. Standard odds are reference values; live payouts may differ.`,'tl-probability-note'));
  const paletteOverview=make('div',undefined,'tl-palette-overview');
  const paletteControls=make('div',undefined,'tl-palette-overview-controls');
  selectionToolbar.before(paletteOverview);paletteControls.append(selectionToolbar,filterBar);
  paletteOverview.append(paletteControls,probability);
  function renderProbability() {
    const state=selectionState();targetSelect.value=state.target;
    targetStatus.textContent=state.target?`Selected ${state.numbers.size} / target ${state.target}${state.numbers.size===Number(state.target)?' · target met':' · count differs from target'}`:`Selected ${state.numbers.size} / 28 · no target`;
    try {
      const result=numberModel.compare(state.numbers);probabilityCards.replaceChildren();probabilityBar.hidden=false;
      [['Selected',result.selected,result.weight,result.percentage],['Unselected',result.unselected,result.otherWeight,result.otherPercentage]].forEach(([label,numbers,weight,percentage])=>{
        const card=make('div',undefined,'tl-probability-card');card.dataset.side=label.toLowerCase();
        card.append(make('h4',`${label} · ${numbers.length} numbers`),make('strong',`${percentage}%`),make('p',`Weight ${weight} / 1,000`));
        if(label==='Selected')card.append(make('p',numbers.join(', ')||'None','tl-selected-list'));probabilityCards.append(card);
      });
      selectedBar.style.width=`${result.percentage}%`;unselectedBar.style.width=`${result.otherPercentage}%`;
      probabilityBar.setAttribute('aria-label',`Selected ${result.percentage}%; unselected ${result.otherPercentage}%`);
      const difference=result.weight-result.otherWeight,sign=difference>0?'+':'';
      probabilityText.textContent=`Selected coverage is ${difference===0?'equal':difference<0?'lower':'higher'}: ${result.percentage}% versus ${result.otherPercentage}%. Difference ${sign}${difference} weight / ${sign}${(difference/10).toFixed(2)} percentage points.`;
      complementList.textContent=result.unselected.join(', ')||'None';
    } catch(error) {probabilityCards.replaceChildren();probabilityBar.hidden=true;complementList.textContent='Unavailable';probabilityText.textContent=error.message;}
  }

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
        marker.append(make('span',`${prefix}${i}`),make('strong','N/A'),make('small',''));map.set(key,marker);
        if(metric==='Gap') {
          const stack=make('div',undefined,'tl-axis-group');
          marker.querySelector('span').textContent='Gap';
          stack.append(marker,groupButton(key,`${prefix}${i}`));container.append(stack);
        } else container.append(marker);
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
  const summaryDisclosure=make('details',undefined,'tl-summary-disclosure');summaryDisclosure.id='tl-row-column-summary';
  summaryDisclosure.append(make('summary','Row & column summary'),compactSummary);root.querySelector('.tl-palette-layout').after(summaryDisclosure);
  const boardHint=make('p','Scroll the board sideways to see all columns and metrics.','tl-board-hint');boardHint.hidden=true;
  const recentStrip=el('recent-results');scroller.after(recentStrip);recentStrip.after(boardHint);
  const updateBoardHint=()=>{boardHint.hidden=scroller.scrollWidth<=scroller.clientWidth+1;};
  const boardObserver=new ResizeObserver(updateBoardHint);boardObserver.observe(scroller);boardObserver.observe(frame);

  // Reuse round buttons across polls so keyboard focus stays on the same round.
  const recentModes=['Number','Size','Parity','Combination'];
  // Match the timeline's category colors even when those tracks are hidden.
  const recentCategoryLegends={
    Size:[['S','Small','#38bdf8'],['B','Big','#34d399']],
    Parity:[['E','Even','#a78bfa'],['O','Odd','#fb923c']],
    Combination:[['SE','Small Even','#38bdf8'],['SO','Small Odd','#fbbf24'],['BE','Big Even','#a78bfa'],['BO','Big Odd','#34d399']]
  };
  let recentMode=0,recentSnapshot=[],recentStream=null,recentFocused=null,recentRecord=null;
  const recentNodes=new Map(),recentHeading=make('div',undefined,'tl-recent-heading');
  const recentCaption=make('span','Newest →','tl-recent-caption');
  const recentView=button('View: Number ↻',cycleRecentView);recentView.id='tl-recent-view';
  const recentDetails=button('Game details',()=>{recentInfo.hidden=!recentInfo.hidden;updateRecentDetails();});recentDetails.id='tl-recent-details';
  recentDetails.setAttribute('aria-controls','tl-recent-info');recentDetails.setAttribute('aria-expanded','false');
  const recentNewest=button('Back to newest',()=>{recentViewport.scrollTop=0;updateRecentScroll();});recentNewest.id='tl-recent-newest';
  recentNewest.setAttribute('aria-controls','tl-recent-viewport');
  recentHeading.append(recentCaption,recentView,recentDetails,recentNewest);
  const recentViewport=make('div',undefined,'tl-recent-viewport');recentViewport.id='tl-recent-viewport';recentViewport.tabIndex=0;
  recentViewport.setAttribute('role','region');recentViewport.setAttribute('aria-label','Latest 150 available results, newest first. Scroll down for older rounds and up for newer rounds.');
  const recentChips=make('div',undefined,'tl-recent-chips');recentChips.setAttribute('role','group');recentChips.setAttribute('aria-label','Recent results; activate a circle to cycle all results through number, size, parity and combination');
  recentViewport.append(recentChips);
  function updateRecentScroll(){recentNewest.disabled=recentViewport.scrollTop<=2;}
  recentViewport.addEventListener('scroll',updateRecentScroll,{passive:true});
  const recentNotice=make('p',undefined,'tl-recent-notice');recentNotice.id='tl-recent-notice';
  const recentInfo=make('div',undefined,'tl-recent-info');recentInfo.id='tl-recent-info';recentInfo.hidden=true;
  const recentInfoText=make('p'),recentLink=make('a');recentLink.className='tl-recent-round-link';recentInfo.append(recentInfoText,recentLink);
  const recentLegend=make('div',undefined,'tl-recent-legend');recentLegend.setAttribute('aria-label','Recent result color key');
  recentStrip.replaceChildren(recentHeading,recentViewport,recentLegend,recentNotice,recentInfo);
  function recentColors() {
    if(recentMode===0)return (data?.stream===el('stream').value?data.group_stats??[]:[])
      .filter(group=>group.family==='Colors').map(group=>({key:group.key,label:group.label,color:group.color,numbers:group.numbers}));
    const track=['number','size','parity','combo'][recentMode];
    return recentCategoryLegends[recentModes[recentMode]].map(([key,label,color])=>({key,label,
      color:data?.tracks?.find(item=>item.tracker_key===track)?.legend.find(item=>item.letter===key)?.color??color}));
  }
  function resultTagText(game,isLatest) {
    const observation=game?.new_repeat,kind=observation?.kind;
    const label=kind==='new'?'New':kind==='repeated'?'Repeated':observation?.reason||'Building history';
    return label+(isLatest&&kind?` · ${kind==='new'?'N':'R'}×${observation.run}`:'');
  }
  function recentClassification(game) {
    const size=game.number<14?'S':'B',parity=game.number%2===0?'E':'O';
    return {size,parity,combo:size+parity};
  }
  function focusRecent(game) {recentFocused=game.game_no;recentRecord=game;updateRecentDetails();}
  function updateRecentDetails() {
    recentDetails.disabled=!recentRecord;
    recentDetails.setAttribute('aria-expanded',String(!recentInfo.hidden));
    if(!recentRecord){recentInfo.hidden=true;recentDetails.setAttribute('aria-expanded','false');recentInfoText.textContent='';recentLink.removeAttribute('href');return;}
    const {size,parity,combo}=recentClassification(recentRecord);
    recentInfoText.textContent=`Number ${recentRecord.number} · ${size==='S'?'Small':'Big'} (${size}) · ${parity==='E'?'Even':'Odd'} (${parity}) · ${combo} · #${recentRecord.game_no} · ${new Date(recentRecord.timestamp).toLocaleString()}${recentRecord.gap_before?' · history gap before this round':''}${paletteStaleMessage?' · last loaded data':''}`;
    recentLink.textContent=`Open round #${recentRecord.game_no} ↗`;recentLink.href=recentRecord.url;
    recentDetails.title=`Details for round #${recentRecord.game_no}`;
  }
  function cycleRecentView() {recentMode=(recentMode+1)%recentModes.length;renderRecent(recentSnapshot);}
  function renderRecent(recent) {
    const stream=el('stream').value;
    if(recentStream!==stream){recentFocused=null;recentRecord=null;recentInfo.hidden=true;recentStream=stream;recentNodes.clear();recentChips.replaceChildren();recentViewport.scrollTop=0;}
    recentSnapshot=recent;
    recentView.textContent=`View: ${recentModes[recentMode]} ↻`;recentView.disabled=!recent.length;
    recentView.setAttribute('aria-label',`View: ${recentModes[recentMode]}. Switch to ${recentModes[(recentMode+1)%recentModes.length]}`);
    recentView.setAttribute('aria-controls','tl-recent-results');
    recentCaption.textContent=`Newest → · ${recent.length} ${recent.length===1?'result':'results'}`;
    const active=document.activeElement,focusedId=recentChips.contains(active)?active.dataset.round:null;
    const scrollTop=recentViewport.scrollTop,viewportTop=recentViewport.getBoundingClientRect().top;
    // Anchor a visible round while new rounds shift the grid. At the top, follow live results.
    const anchor=scrollTop>2?[...recentChips.children].find(node=>node.getBoundingClientRect().bottom>viewportTop):null;
    const anchorOffset=anchor?anchor.getBoundingClientRect().top-viewportTop:0;
    const colors=recentColors();
    recentLegend.replaceChildren(...colors.map(item=>{
      const entry=make('span'),swatch=make('i');swatch.style.backgroundColor=item.color;swatch.setAttribute('aria-hidden','true');
      entry.append(swatch,document.createTextNode(recentMode===0?item.label:`${item.key} · ${item.label}`));
      if(item.numbers)entry.title=item.numbers.join(', ');return entry;
    }));
    recentLegend.hidden=!recent.length;
    const ids=new Set(recent.map(game=>game.game_no));
    recentNodes.forEach((node,id)=>{if(!ids.has(id)){node.remove();recentNodes.delete(id);}});
    recent.forEach((game,index)=>{
      let control=recentNodes.get(game.game_no);
      if(!control){
        control=button('',()=>{focusRecent(control.roundRecord);cycleRecentView();});control.className='tl-recent-chip';control.dataset.round=game.game_no;
        control.append(make('span',undefined,'tl-recent-circle'),make('small',undefined,'tl-new-repeat'));
        control.addEventListener('focus',()=>focusRecent(control.roundRecord));recentNodes.set(game.game_no,control);
      }
      control.roundRecord=game;
      const {size,parity,combo}=recentClassification(game),label=[game.number,size,parity,combo][recentMode];
      const colorGroup=colors.find(item=>recentMode===0?item.numbers.includes(game.number):item.key===label);
      control.style.setProperty('--recent-color',colorGroup?.color??'#aab0bb');
      control.dataset.colorGroup=colorGroup?.key??'unknown';
      control.firstChild.textContent=label;
      const observation=game.new_repeat,kind=observation?.kind;
      const badge=control.querySelector('.tl-new-repeat');
      badge.textContent=resultTagText(game,index===0);
      badge.dataset.kind=kind??'unknown';
      badge.title=kind?'Compared with the ten completed rounds before this result.':'Ten continuous prior results are required.';
      control.classList.toggle('is-latest',index===0);control.classList.toggle('has-gap',Boolean(game.gap_before));
      control.title=`${index===0?'Newest · ':''}#${game.game_no} · Number ${game.number} · ${size} · ${parity} · ${combo} · ${colorGroup?.label??'Color unavailable'} · ${formatTime(game.timestamp)} · ${badge.textContent}${game.gap_before?' · history gap before this round':''}`;
      control.setAttribute('aria-label',`${control.title}. Showing ${recentModes[recentMode]} ${label}. Activate to show ${recentModes[(recentMode+1)%recentModes.length]} for all results.`);
      // Inserting a new round leaves unchanged nodes in place.
      if(recentChips.children[index]!==control)recentChips.insertBefore(control,recentChips.children[index]??null);
    });
    if(focusedId){const target=recentNodes.get(focusedId)??recentView;if(document.activeElement!==target)target.focus({preventScroll:true});}
    recentViewport.scrollTop=anchor?.isConnected?scrollTop+anchor.getBoundingClientRect().top-viewportTop-anchorOffset:scrollTop;
    updateRecentScroll();
    if(recentFocused)recentRecord=recent.find(game=>game.game_no===recentFocused)??recentRecord;
    if(!recentRecord && recent.length)focusRecent(recent[0]);
    updateRecentDetails();
    recentNotice.textContent=!recent.length?'Recent history unavailable.':[
      recent.length>10?'Scroll down for older results · up for newer results':'',
      paletteStaleMessage?'Last loaded results · updates unavailable':'',
      recent.some(game=>game.gap_before)?'History gaps marked · latest available completed results':''
    ].filter(Boolean).join(' · ');
    recentNotice.hidden=!recentNotice.textContent;
  }


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
  const chartNote = make('p','Gaps count saved completed games, independently of number selection. 0 = appeared in the latest result. + = not seen in available history. * = missing or unverified rounds; observed count only. Averages and maxima exclude intervals marked *.','tl-gap-note');
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
  const metricDisclosure=make('details',undefined,'tl-metric-disclosure');
  metricDisclosure.append(make('summary','How gaps and streaks work'),make('p',metricHelp,'tl-metric-help'));summaryDisclosure.after(metricDisclosure);
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
    const historyButton = button('View gap history ↓', () => {gapMode = 'history'; chartGroup = group.key; gapFamily = group.family; renderGaps(); analytics.scrollIntoView({behavior:'smooth',block:'start'});});
    historyButton.className = 'tl-group-apply'; panel.append(historyButton);
  }
  renderGaps();

  function paletteUnavailable(message, clear=false) {
    paletteStaleMessage=message;
    renderPalette(clear);
  }

  function renderPalette(clear=false) {
    const available=!clear && data?.stream===el('stream').value;
    renderGaps(!available);
    const seen=new Set(),history=available?data.games.filter(game=>{if(seen.has(game.game_no))return false;seen.add(game.game_no);return true;}):[];
    const recent=history.slice(0,10),counts=new Map();recent.forEach(game=>counts.set(game.number,(counts.get(game.number)??0)+1));
    historyReady=recent.length>0;recentMembers=[...counts.keys()];
    const state=selectionState(),latestNumber=recent[0]?.number??null;
    if(state.mode==='auto' && available)state.numbers=new Set(recentMembers);
    selectionStatus.textContent=`Mode: ${state.mode==='auto'?'Auto last 10':'Manual'} · ${state.numbers.size} selected · ${counts.size} recent distinct${paletteStaleMessage?' · '+(available?'last loaded data':'waiting for history'):''}`;
    groupButtons.forEach(({control,label},key)=>{
      const members=membersFor(key),count=members.filter(n=>state.numbers.has(n)).length,full=members.length>0&&count===members.length;
      control.disabled=!members.length;control.setAttribute('aria-pressed',String(full));
      control.querySelector('small').textContent=`${count}/${members.length}`;
      control.setAttribute('aria-label',`${full?'Deselect':'Select'} ${label}: ${count} of ${members.length} selected`);
    });
    root.querySelector('.tl-palette-section').classList.toggle('stale',Boolean(paletteStaleMessage));el('palette').setAttribute('aria-busy','false');
    el('palette-status').textContent=paletteStaleMessage || (recent.length?`Last ${recent.length} available completed results · ${counts.size} distinct · #${data.latest_game_id} · checked ${formatTime(data.checked_at)}${data.has_gaps?' · history gaps marked':''}`:'History unavailable · no completed results yet. Manual selection remains available.');
    paletteTiles.forEach((tile,number)=>{
      const hits=counts.get(number)??0,isSelected=state.numbers.has(number),control=tile.querySelector('.tl-tile-toggle');
      tile.classList.toggle('number-selected',isSelected);control.setAttribute('aria-pressed',String(isSelected));
      control.setAttribute('aria-label',`${isSelected?'Deselect':'Select'} number ${number}${historyReady?`: ${hits} hits in last ${recent.length} results`:': recent history unavailable'}`);
      tile.querySelector('.tl-tile-hits').textContent=historyReady?`${hits} ${hits===1?'hit':'hits'}`:'N/A';
      tile.querySelector('.tl-latest-badge').hidden=number!==latestNumber;
      // A tile represents a number: use its newest occurrence in the displayed
      // ten, never infer New from zero hits or from manual selection.
      const appearance=recent.find(game=>game.number===number),resultTag=tile.querySelector('.tl-palette-result-tag');
      resultTag.hidden=!appearance;
      resultTag.textContent=appearance?resultTagText(appearance,appearance===recent[0]):'';
      resultTag.dataset.kind=appearance?.new_repeat?.kind??'unknown';
      resultTag.title=appearance?`Most recent appearance in the latest ${recent.length}: #${appearance.game_no}. Compared with the ten rounds before that result.`:'';
      if(appearance)control.setAttribute('aria-label',`${control.getAttribute('aria-label')}. ${resultTag.textContent}`);
    });
    renderProbability();
    renderRecent(history.slice(0,150));
    const panel=el('number-detail');panel.replaceChildren();
    if(available && focusedGroup && groupFor(focusedGroup)){renderGroupDetail(panel,groupFor(focusedGroup));return;}
    if(focusedNumber===null){panel.append(make('h3','Number details'),make('p','Use Details below a number to inspect it. The number button changes selection.'));return;}
    panel.append(make('div',focusedNumber,'tl-number-hero'),make('h3',`Number ${focusedNumber}`));
    try {
      numberModel.compare([focusedNumber]);
      const record=numberModel.model.records.find(r=>r.number===focusedNumber);
      panel.append(make('p',`Probability weight: ${record.weight} / 1,000 · Modeled probability: ${(record.weight/10).toFixed(2)}%`),
        make('p',`Standard odds reference: ${record.odds}. Live payouts may differ.`));
    }catch(error){panel.append(make('p',error.message));}
    const stat=available?data.number_stats.find(s=>s.number===focusedNumber):null;
    if(!stat || !historyReady){panel.append(make('p','Recent appearances and gaps unavailable.'));return;}
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

  function markChecked(checkedAt) {
    if(!data)return;
    data.checked_at=checkedAt;
    const checked=` · checked ${formatTime(checkedAt)}`;
    for(const node of [el('palette-status'),el('gap-status')])if(node)node.textContent=node.textContent.replace(/ · checked [^·]+/,checked+' ');
    status(`${paused ? 'Paused' : 'Live · checks every 1s'}${checked} · latest ${data.latest_game_id ? '#'+data.latest_game_id : 'waiting'}${data.has_gaps?' · history gaps marked':''}`);
  }
  async function fetchData() {
    if (busy) {pending = true; return;}
    clearTimeout(pollTimer);
    busy = true;
    let failed=false;
    const startedAt=performance.now();
    const requestedStream = el('stream').value;
    const requestedTracks = enabled === null ? null : enabled.join(',');
    try {
      const url = new URL(root.dataset.feed, location.origin); url.searchParams.set('stream', requestedStream);
      if (requestedTracks !== null) url.searchParams.set('tracks', requestedTracks);
      const requestKey=url.toString();
      const headers=feedKey===requestKey && data?.stream===requestedStream && feedETag?{'If-None-Match':feedETag}:{};
      const response = await fetch(url, {cache: 'no-store', headers, signal: AbortSignal.timeout(12000)});
      if (requestedStream !== el('stream').value || requestedTracks !== (enabled === null ? null : enabled.join(','))) {pending = true; return;}
      if(response.status===304 && data) {
        const recovered=Boolean(paletteStaleMessage);paletteStaleMessage='';
        if(recovered)renderPalette();
        markChecked(response.headers.get('X-Timeline-Checked-At')||new Date().toISOString());return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const next = await response.json();
      if (requestedStream !== el('stream').value || requestedTracks !== (enabled === null ? null : enabled.join(','))) {pending = true; return;}
      if (enabled === null) {enabled = next.catalog.map(t => t.key); write('lucky28.timeline.tracks', enabled);}
      const recovered=Boolean(paletteStaleMessage);
      data = next;
      feedETag=response.headers.get('ETag')||'';feedKey=requestKey;
      paletteStaleMessage = '';
      const nextSignature = JSON.stringify([data.games, data.tracks, data.number_stats, data.group_stats, data.observed_games]);
      if (nextSignature !== signature) {render(); signature = nextSignature;}
      else if(recovered)renderPalette();
      const settingsSignature=JSON.stringify([data.catalog,data.streams,enabled]);
      if(root.dataset.settingsSignature!==settingsSignature){settings();root.dataset.settingsSignature=settingsSignature;}
      markChecked(data.checked_at);
    } catch (error) {
      failed=true;
      status(`Refresh failed — ${data ? 'showing last loaded results' : 'history unavailable'}. Retrying in 5s. (${error.message})`, true);
      paletteUnavailable(data && data.stream === el('stream').value ? 'Updates unavailable · showing the last loaded palette and details.' : 'History unavailable. Retrying automatically.');
    }
    finally {
      busy=false;
      if(pending){pending=false;fetchData();}
      else pollTimer=setTimeout(()=>{if(!paused&&!document.hidden)fetchData();},failed?5000:Math.max(100,pollDelay-(performance.now()-startedAt)));
    }
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
  root.querySelector('.tl-footnote').textContent='Checks every second while visible; unchanged responses do not redraw the page. New/Repeated compares each result with its previous ten rounds. Dashed borders mark history gaps. Alert markers show recorded events.';
  renderPalette();
  fetchData();
})();
