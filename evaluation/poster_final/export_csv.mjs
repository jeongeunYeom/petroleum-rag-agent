// CSV-only research tables: typed values, no hidden sheets or presentation workbook.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
const out=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(path.resolve(out,'../../data/v14-poster-export/entry.mjs'));
const {Workbook}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const tables=JSON.parse(await fs.readFile(path.join(out,'csv_tables.json'),'utf8'));
const checks=[];
for(const [name,rows] of Object.entries(tables)){
  const book=Workbook.create();const sheet=book.worksheets.add('Results');
  const width=rows[0].length;
  if(!rows.every(row=>row.length===width))throw Error('Nonrectangular table '+name);
  const clean=rows.map(row=>row.map(v=>typeof v==='string'&&/^[=+@]/.test(v)?"'"+v:v));
  sheet.getRangeByIndexes(0,0,clean.length,width).values=clean;
  book.recalculate();
  const values=sheet.getRangeByIndexes(0,0,clean.length,width).values;
  if(JSON.stringify(values)!==JSON.stringify(clean))throw Error('Cell values changed '+name);
  const csv=values.map(row=>row.map(v=>{
    const text=v===null?'':String(v);
    return /[",\r\n]/.test(text)?'"'+text.replaceAll('"','""')+'"':text;
  }).join(',')).join('\r\n')+'\r\n';
  await fs.writeFile(path.join(out,name),csv,'utf8');
  checks.push({file:name,rows:values.length-1,columns:width,typed_roundtrip:true});
}
await fs.writeFile(path.join(out,'csv_validation.json'),JSON.stringify(checks,null,2)+'\n');
console.log(JSON.stringify(checks));
