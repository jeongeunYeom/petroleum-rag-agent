import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {Workbook} from '@oai/artifact-tool';
const dir=path.dirname(fileURLToPath(import.meta.url));
if(process.argv.includes('--help-csv')) {
  const wb=Workbook.create();
  console.log(wb.help('workbook.toCSV',{include:'index,examples,notes',maxChars:3500}).ndjson);
} else {
  const tables=JSON.parse(await fs.readFile(path.join(dir,'table_data.json'),'utf8'));
  const checks=[];
  for(const [name,rows] of Object.entries(tables)) {
    const wb=Workbook.create();const sheet=wb.worksheets.add('Results');
    sheet.getRangeByIndexes(0,0,rows.length,rows[0].length).values=rows;
    wb.recalculate();
    checks.push({name,inspection:(await wb.inspect({kind:'table',range:`Results!A1:D${Math.min(rows.length,5)}`,include:'values',tableMaxRows:5,tableMaxCols:4})).ndjson});
    const values=sheet.getRangeByIndexes(0,0,rows.length,rows[0].length).values;
    const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';
    await fs.writeFile(path.join(dir,name),values.map(row=>row.map(quote).join(',')).join('\r\n')+'\r\n','utf8');
    // CSV has no layout, formulas or native workbook styling to preserve.
    if(JSON.stringify(values)!==JSON.stringify(rows))throw new Error('CSV values changed: '+name);
    if(name==='poster_rag_effect.csv'||name==='poster_reference_metrics.csv'||name==='poster_category_metrics.csv'){
      sheet.getUsedRange().format.columnWidth=24;
      sheet.getUsedRange().format.rowHeight=32;
      sheet.getUsedRange().format.wrapText=true;
      sheet.getRangeByIndexes(0,0,1,rows[0].length).format.font={bold:true};
      wb.recalculate();
      const preview=await wb.render({sheetName:'Results',autoCrop:'all',scale:1,format:'png'});
      const destination=path.join(os.tmpdir(),'v16-'+name+'.png');
      await fs.writeFile(destination,new Uint8Array(await preview.arrayBuffer()));
      checks.at(-1).preview=destination;
    }
  }
  await fs.writeFile(path.join(dir,'table_export_checks.json'),JSON.stringify(checks,null,2));
}
