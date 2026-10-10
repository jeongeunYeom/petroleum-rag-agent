// CSV deliverables are authored through an artifact-tool workbook, then serialized
// without adding an unrequested XLSX file to the evaluation repository.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook } from '@oai/artifact-tool';

const root = path.dirname(fileURLToPath(import.meta.url));
const input = JSON.parse(await fs.readFile(path.join(root, 'metrics', 'csv_input.json'), 'utf8'));

function columnName(index) {
  let name = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    name = String.fromCharCode(65 + (n - 1) % 26) + name;
  }
  return name;
}

function csvCell(value) {
  let text = value === null || value === undefined ? '' :
    (typeof value === 'object' ? JSON.stringify(value) : String(value));
  if (typeof value === 'string' && /^[=+@-]/.test(text)) text = "'" + text;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

for (const [name, data] of Object.entries(input)) {
  const matrix = [data.columns, ...data.rows.map(row => data.columns.map(key => row[key] ?? null))];
  if (!matrix.length || matrix.some(row => row.length !== data.columns.length)) {
    throw new Error(`Nonrectangular CSV matrix: ${name}`);
  }
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add(name);
  sheet.getRange('A1').write(matrix);
  workbook.recalculate();
  const end = `${columnName(data.columns.length - 1)}${matrix.length}`;
  const readback = sheet.getRange(`A1:${end}`).values;
  if (readback.length !== matrix.length || readback[0].join('|') !== data.columns.join('|')) {
    throw new Error(`Artifact-tool validation failed: ${name}`);
  }
  const inspection = await workbook.inspect({ kind: 'sheet', include: 'id,name' });
  if (!inspection) throw new Error(`Artifact-tool inspect failed: ${name}`);
  const csv = readback.map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
  await fs.writeFile(path.join(root, `${name}.csv`), '\ufeff' + csv, 'utf8');
  console.log(`${name}.csv rows=${readback.length - 1} columns=${data.columns.length}`);
}
