import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const require=createRequire('file:///C:/Users/petro-T7920/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/package.json');
const {Workbook}=require('@oai/artifact-tool');
const root=path.dirname(fileURLToPath(import.meta.url));
const matrices=JSON.parse(await fs.readFile(path.join(root,'csv_matrices.json'),'utf8'));
const checks=[];
for(const [name,matrix] of Object.entries(matrices)) {
  const workbook=Workbook.create();
  const sheet=workbook.worksheets.add('Results');
  sheet.showGridLines=false;
  const range=sheet.getRangeByIndexes(0,0,matrix.length,matrix[0].length);
  range.values=matrix;
  workbook.recalculate();
  const actual=range.values;
  assert.deepEqual(actual,matrix);
  // CSV export is not exposed in bundled public API/help. Serialize verified
  // artifact-tool-authored cell values with RFC 4180 quoting; no XLSX substitute.
  const quote=v=>v===null?'':'"'+String(v).replaceAll('"','""')+'"';
  const csv=actual.map(row=>row.map(quote).join(',')).join('\r\n')+'\r\n';
  await fs.writeFile(path.join(root,name),csv,'utf8');
  checks.push({file:name,rows:matrix.length-1,columns:matrix[0].length,typed_roundtrip_equal:true});
  console.log(name,matrix.length-1,'rows');
}
await fs.writeFile(path.join(root,'csv_verification.json'),JSON.stringify(checks,null,2)+'\n');
