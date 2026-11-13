import app from '../App.tsx?raw'
import { describe, expect, test } from 'vitest'
import { NAV_GROUPS, findNav, toggleGroup } from './nav'

const items = NAV_GROUPS.flatMap((g) => g.items)

describe('nav config', () => {
  test('every route is unique', () => {
    const paths = items.map((i) => i.to)
    expect(new Set(paths).size).toBe(paths.length)
    expect(new Set(NAV_GROUPS.map((g) => g.id)).size).toBe(NAV_GROUPS.length)
  })
  test('every item path is routed in App.tsx', () => {
    for (const i of items) expect(app).toContain(`path="${i.to}"`)
  })
  test('group of the active path is found', () => {
    expect(findNav('/bank')?.group.id).toBe('banking')
    expect(findNav('/trial-balance')?.group.label).toBe('Reports')
    expect(findNav('/vouchers/new')?.item.label).toBe('New voucher')
    expect(findNav('/vouchers')?.item.label).toBe('Vouchers')
    expect(findNav('/vouchers/abc-123')?.item.label).toBe('Vouchers')
    expect(findNav('/nowhere')).toBeNull()
  })
  test('toggleGroup opens and closes', () => {
    expect(toggleGroup([], 'banking')).toEqual(['banking'])
    expect(toggleGroup(['banking', 'masters'], 'banking')).toEqual(['masters'])
  })
})
