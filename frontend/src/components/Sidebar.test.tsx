import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, test } from 'vitest'
import Sidebar from './Sidebar'

const html = (path: string) =>
  renderToString(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar />
    </MemoryRouter>,
  )

describe('Sidebar', () => {
  test('active group is auto-opened, others collapsed', () => {
    const out = html('/brs')
    expect(out).toMatch(/aria-expanded="true"[^>]*title="Banking"/)
    expect(out).toMatch(/aria-expanded="false"[^>]*title="Masters"/)
    expect(out).toContain('BRS report')
    expect(out).not.toContain('Trial Balance')
  })
  test('active item is highlighted', () => {
    expect(html('/vouchers/new')).toMatch(/aria-current="page"[^>]*>New voucher/)
  })
  test('collapse toggle button is present', () => {
    expect(html('/clients')).toContain('Collapse sidebar')
  })
})
