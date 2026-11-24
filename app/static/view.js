import {element, pretty} from './client.js';

const labels = {READY:'通过', MISMATCH:'差异待复核', PENDING:'待复核', APPROVED:'已签发', HELD:'已暂缓'};
const headers = ['业务分组', '基准版本', '输入行', '计算值', '参考值', '判定'];

export function badge(status) {
  return element('span', labels[status] || status, {class:'badge', 'data-result':status, title: status});
}

export function snapshot(report, selected, stage) {
  const stats = report.intake;
  document.querySelector('[data-metric="input"]').textContent = stats.input;
  document.querySelector('[data-metric="accepted"]').textContent = stats.accepted;
  document.querySelector('[data-metric="isolated"]').textContent = stats.rejected;
  document.querySelector('[data-metric="cases"]').textContent = report.cases?.length ?? '—';
  const table = document.querySelector('#rows');
  table.replaceChildren();
  const head = element('tr');
  const body = table.createTBody();
  if (stage === 'intake') {
    head.append(...['源行', '记录键', '业务分组', '原因码'].map(title => element('th', title, {scope:'col'})));
    for (const item of stats.isolation) {
      const tr = body.insertRow();
      tr.append(...[item.line,item.record,item.case,item.reason].map(value=>element('td',value)));
    }
    if (!stats.isolation.length) body.insertRow().insertCell().textContent = '当前文件没有隔离行';
  } else {
    head.append(...headers.map(title => element('th', title, {scope:'col'})));
    for (const row of report.cases || []) {
      const tr = body.insertRow();
      const button = element('button',row.case,{type:'button','data-case':row.case,'aria-pressed':String(row.case===selected)});
      tr.insertCell().append(button);
      const version = row.baseline?.version || '—';
      tr.insertCell().textContent = row.pinned ? `${version}（冻结）` : version;
      [row.records.length, row.measure?.value ?? '—', row.measure?.expected ?? '—'].forEach(value=>tr.insertCell().textContent=value);
      tr.insertCell().append(badge(row.status));
    }
  }
  table.createTHead().append(head);
  const picked = report.cases?.find(row=>row.case===selected);
  document.querySelector('#detail-title').textContent = picked ? `分组 ${picked.case}` : '采信摘要';
  const shown = picked ? picked.measure?.evidence ?? picked.prep?.details ?? {原因:picked.status} : stats.reasons;
  document.querySelector('#detail').textContent = pretty(shown);
  document.querySelector('#counts').textContent = report.balance ? `行数 ${report.balance.accounted}/${report.balance.input} · ${report.balance.ready} 组通过` : `采信 ${stats.accepted} 行 · 隔离 ${stats.rejected} 行`;
  calibration(report.calibration, report.cases || []);
}

function calibration(cal, cases) {
  const set = (selector, text) => { const node = document.querySelector(selector); if (node) node.textContent = text; };
  set('#cal-version', cal?.version || '—');
  set('#cal-previous', cal?.previous_version || '尚无生效版本');
  set('#cal-affected', cal?.affected?.length ? cal.affected.join('、') : '无');
  const state = document.querySelector('#baseline-state');
  if (state) {
    if (!cal) { state.textContent = '—'; state.dataset.result = ''; }
    else if (cal.blocked?.length) { state.textContent = `阻断 · ${cal.blocked.length} 处无法闭合`; state.dataset.result = 'MISMATCH'; }
    else if (cal.releasable === null) { state.textContent = '预览 · 未做整批对账'; state.dataset.result = ''; }
    else if (cal.releasable) { state.textContent = cal.previous_version ? '可发布 · 已采用新基准' : '可发布'; state.dataset.result = 'READY'; }
    else { state.textContent = '不可发布'; state.dataset.result = 'MISMATCH'; }
  }
  const table = document.querySelector('#changes');
  if (!table) return;
  const pinned = new Set((cal?.issued || []).map(item => `${item.case}/${item.record}`));
  const rows = [
    ...(cal?.changes || []).map(change => ({...change, kind: change.applied ? '已采用新基准' : '保持签发值'})),
    ...(cal?.blocked || []).map(block => ({case: block.case, record: block.record, value: null, kind: `阻断 · ${block.reason}`})),
  ];
  table.replaceChildren();
  const head = element('tr');
  head.append(...['业务分组', '读数记录', '原值', '新值', '状态'].map(title => element('th', title, {scope:'col'})));
  const body = table.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    const frozen = row.pinned || pinned.has(`${row.case}/${row.record}`);
    [row.case, row.record || '—', row.previous ?? '—', row.value ?? '—'].forEach(value => tr.insertCell().textContent = value);
    tr.insertCell().append(element('span', frozen ? `${row.kind} · 冻结` : row.kind, {class: 'badge', 'data-result': row.value === null ? 'MISMATCH' : 'READY'}));
  }
  if (!rows.length) body.insertRow().insertCell().textContent = cal?.previous_version ? '本版无变化读数' : '首次发布，无可对照的旧读数';
  table.createTHead().append(head);
}

export function history(items, active) {
  const target = document.querySelector('#history');
  target.replaceChildren();
  for (const run of items) {
    const button = element('button', run.id.slice(0,10), {'data-run':run.id,'aria-pressed':String(run.id===active),type:'button'});
    const item = element('li');
    item.append(button, badge(run.status));
    target.append(item);
  }
  if (!items.length) target.append(element('li','尚无执行批次'));
}
