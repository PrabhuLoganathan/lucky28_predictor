/* Fixed theoretical model; never inferred from history or payout odds. */
(function (root) {
  'use strict';
  const weights = [1,3,6,10,15,21,28,36,45,55,63,69,73,75,75,73,69,63,55,45,36,28,21,15,10,6,3,1];
  const odds = ['1000.0','333.3','166.7','100.0','66.7','47.6','35.7','27.8','22.2','18.2','15.9','14.5','13.7','13.3'];
  const model = Object.freeze({version:'uniform-three-digits-v1', total:1000,
    label:'Theoretical model: three independent uniform digits, 0–9',
    records:Object.freeze(weights.map((weight,number)=>Object.freeze({number,weight,odds:odds[Math.min(number,27-number)]})))});
  const validNumber = n => Number.isInteger(n) && n >= 0 && n <= 27;
  function validate(source) {
    if (!source || !source.version || source.total !== 1000 || !Array.isArray(source.records) || source.records.length !== 28 ||
        new Set(source.records.map(r=>r?.number)).size !== 28 || source.records.some(r=>!r || !validNumber(r.number) ||
          !Number.isInteger(r.weight) || r.weight <= 0 || typeof r.odds !== 'string' || !/^\d+\.\d$/.test(r.odds) || Number(r.odds)<=0) ||
        source.records.reduce((sum,r)=>sum+r.weight,0)!==1000) throw new Error('Calculation error: incomplete or invalid probability model.');
  }
  function compare(values, source=model) {
    validate(source);
    const selected = [...new Set(values)];
    if (selected.some(n=>!validNumber(n))) throw new Error('Calculation error: selected numbers must be integers from 0 to 27.');
    selected.sort((a,b)=>a-b);
    const chosen = new Set(selected), unselected = source.records.map(r=>r.number).filter(n=>!chosen.has(n)).sort((a,b)=>a-b);
    const weight = source.records.reduce((sum,r)=>sum+(chosen.has(r.number)?r.weight:0),0);
    return {selected,unselected,weight,otherWeight:1000-weight,percentage:(weight/10).toFixed(2),otherPercentage:((1000-weight)/10).toFixed(2)};
  }
  function toggle(values, members) {
    const next = new Set(values), group = [...new Set(members)];
    if ([...next,...group].some(n=>!validNumber(n))) throw new Error('Invalid selection group.');
    const remove = group.length > 0 && group.every(n=>next.has(n));
    group.forEach(n=>remove?next.delete(n):next.add(n));
    return next;
  }
  const api=Object.freeze({model,compare,toggle});
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.Lucky28Numbers=api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
