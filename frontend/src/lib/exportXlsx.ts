/** Download a sheet as .xlsx. Cells are written as text exactly as shown (Indian format) so nothing is re-parsed.
 *  SheetJS is loaded on demand so it does not weigh down every page. */
export async function exportXlsx(filename: string, title: string, header: string[], rows: string[][]): Promise<void> {
  const XLSX = await import('xlsx')
  const sheet = XLSX.utils.aoa_to_sheet([[title], [], header, ...rows])
  sheet['!cols'] = header.map((h, i) => ({ wch: Math.max(h.length, ...rows.map((r) => (r[i] ?? '').length), 10) + 2 }))
  const book = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(book, sheet, title.slice(0, 31).replace(/[\\/?*[\]:]/g, ' '))
  XLSX.writeFile(book, filename)
}
