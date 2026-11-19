// Maps an API failure (see docs/API_CONTRACT.md "Errors") to one object the screens can show.

export interface RuleError {
  rule_id: string
  message: string
  line_no: number | null
}

export class ApiFailure {
  status: number
  code: string
  message: string
  details: unknown
  ruleErrors: RuleError[]
  constructor(status: number, code: string, message: string, details: unknown = null, ruleErrors: RuleError[] = []) {
    this.status = status
    this.code = code
    this.message = message
    this.details = details
    this.ruleErrors = ruleErrors
  }
}

interface PydanticItem {
  loc?: unknown[]
  msg?: string
}

function describePydantic(items: PydanticItem[]): string {
  return items
    .map((i) => {
      const where = (i.loc ?? []).filter((p) => p !== 'body').join(' > ')
      return where ? `${where}: ${i.msg ?? 'invalid'}` : (i.msg ?? 'invalid')
    })
    .join('; ')
}

/** body = the parsed JSON of the failed response (or null when it was not JSON). */
export function mapApiError(status: number, body: unknown): ApiFailure {
  const obj = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>
  if (Array.isArray(obj.errors)) {
    const rule = (obj.errors as RuleError[]).map((e) => ({
      rule_id: e.rule_id,
      message: e.message,
      line_no: e.line_no ?? null,
    }))
    return new ApiFailure(status, 'rule_violation', rule.map((e) => e.message).join('; '), null, rule)
  }
  if (typeof obj.code === 'string') {
    return new ApiFailure(status, obj.code, String(obj.message ?? obj.code), obj.details ?? null)
  }
  if (Array.isArray(obj.detail)) {
    return new ApiFailure(status, 'invalid_request', describePydantic(obj.detail as PydanticItem[]))
  }
  if (typeof obj.detail === 'string') return new ApiFailure(status, 'error', obj.detail)
  return new ApiFailure(status, 'error', status === 0 ? 'The server is not reachable.' : `Request failed (HTTP ${status}).`)
}

/** Rule errors of one voucher line (1-based line_no). */
export function errorsForLine(errors: RuleError[], lineNo: number): RuleError[] {
  return errors.filter((e) => e.line_no === lineNo)
}

/** The voucher-level ones (line_no null). */
export function voucherLevelErrors(errors: RuleError[]): RuleError[] {
  return errors.filter((e) => e.line_no === null)
}

/** "line 2" for a rule error that belongs to one voucher line, otherwise empty. */
export function lineLabel(e: Pick<RuleError, 'line_no'>): string {
  return e.line_no === null || e.line_no === undefined ? '' : `line ${e.line_no}`
}

/** Row-by-row problems of a rejected file import (details = [{row, message}]), as readable lines; empty for any other details. */
export function detailLines(details: unknown): string[] {
  if (!Array.isArray(details)) return []
  return details
    .filter((d): d is { row?: unknown; message: string } => !!d && typeof d === 'object' && typeof (d as { message?: unknown }).message === 'string')
    .map((d) => (d.row === undefined || d.row === null || d.row === 0 ? d.message : `Row ${String(d.row)}: ${d.message}`))
}
