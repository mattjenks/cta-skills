import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

const PANE = 'cta-reports'
const DATE = /^\d{4}-\d{2}-\d{2}$/
const REC_ID = /^\d{4}-\d{2}-\d{2}-R\d+$/
const ISSUE = /^https:\/\/github\.com\/\S+$/
const DECISIONS = ['accept', 'defer', 'reject']
const SHOWN = 5

// Change a tag when the value's fields change: it declines what an earlier
// version stored, which outlives a reload.
const selected = atom({ plugin: 'learn', key: 'selected' } as const, '', {
  shape: 'selected-1',
})
const drafts = atom(
  { plugin: 'learn', key: 'drafts' } as const,
  {} as Record<string, string>,
  { shape: 'drafts-1' },
)

type Row = { id: string; decision: string; issue_url: string }
type Rec = { id: string; skill: string; problem: string }
// roots: the live checkout first, then worktrees; reportRoots: where a dated
// report may live besides the live checkout.
type Sources = { roots: string[]; reportRoots: Map<string, string[]> }

// Control characters and newlines to a space, so report text and a typed
// reason stay one line.
const clean = (text: unknown): string =>
  String(text ?? '')
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .trim()

// Only two keys are needed from the CTA config: top-level `kb` and `kb_dir`
// inside [learn]. Quoted string values only.
function parseConfig(text: string, home: string): { kb?: string; kbDir: string } {
  let section = ''
  let kb: string | undefined
  let kbDir = 'learn'
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    const head = /^\[([^\]]*)\]\s*(#.*)?$/.exec(line)
    if (head) {
      section = (head[1] ?? '').trim()
      continue
    }
    const kv = /^([A-Za-z_]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/.exec(line)
    if (!kv) continue
    const value = kv[2] ?? kv[3] ?? ''
    if (section === '' && kv[1] === 'kb') {
      const full =
        value === '~' ? home : value.startsWith('~/') ? `${home}/${value.slice(2)}` : value
      if (full.startsWith('/')) kb = full
    } else if (section === 'learn' && kv[1] === 'kb_dir') {
      const ok = value.trim() !== '' && !value.startsWith('/') && !value.split('/').includes('..')
      kbDir = ok ? value : 'learn'
    }
  }
  return { kb, kbDir }
}

async function readText($: any, path: string): Promise<string | undefined> {
  try {
    return await $.fs.read(path)
  } catch {
    return undefined
  }
}

async function readJson($: any, path: string): Promise<unknown> {
  const text = await readText($, path)
  if (text === undefined) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

async function sources($: any): Promise<Sources | undefined> {
  const home = await $.env.get('HOME')
  if (!home) return undefined
  const config = await readText($, `${home}/.config/cta/config.toml`)
  if (config === undefined) return undefined
  const { kb, kbDir } = parseConfig(config, home)
  if (!kb) return undefined

  // A new report lives in a worktree until its pull request merges.
  const trees = `${home}/.local/share/cta/kb-worktrees`
  let names: string[] = []
  try {
    names = (await $.fs.list(trees)).map((entry: { name: string }) => entry.name)
  } catch {
    names = []
  }
  const live = `${kb}/${kbDir}`
  const reportRoots = new Map<string, string[]>()
  const decisionRoots: string[] = []
  const worktreeRoots: string[] = []
  for (const name of names) {
    const dated = /^learn-report-(\d{4}-\d{2}-\d{2})$/.exec(name)
    if (dated) {
      reportRoots.set(dated[1] ?? '', [live, `${trees}/${name}/${kbDir}`])
      worktreeRoots.push(`${trees}/${name}/${kbDir}`)
    } else if (name === 'learn-decisions') {
      decisionRoots.push(`${trees}/${name}/${kbDir}`)
    }
  }
  return { roots: [live, ...decisionRoots, ...worktreeRoots], reportRoots }
}

// S8: each date is checked before it is listed or used in a path.
async function listDates($: any, src: Sources): Promise<string[]> {
  const seen = new Set<string>()
  for (const root of src.roots) {
    const entries = await readJson($, `${root}/reports/index.json`)
    if (!Array.isArray(entries)) continue
    for (const entry of entries) {
      const date = entry && typeof entry === 'object' ? (entry as { date?: unknown }).date : undefined
      if (typeof date === 'string' && DATE.test(date)) seen.add(date)
    }
  }
  return [...seen].sort().reverse().slice(0, SHOWN)
}

// The latest row of an ID wins; the live log is read first.
async function loadDecisions($: any, src: Sources): Promise<Map<string, Row>> {
  const rows = new Map<string, Row>()
  for (const root of src.roots) {
    const text = await readText($, `${root}/decisions.jsonl`)
    for (const line of (text ?? '').split('\n')) {
      let row: any
      try {
        row = JSON.parse(line)
      } catch {
        continue
      }
      if (row && typeof row.id === 'string' && typeof row.decision === 'string') {
        rows.set(row.id, {
          id: row.id,
          decision: row.decision,
          issue_url: String(row.issue_url ?? ''),
        })
      }
    }
  }
  return rows
}

async function loadReport(
  $: any,
  src: Sources,
  date: string,
): Promise<{ md: string | undefined; recs: Rec[] }> {
  const roots = src.reportRoots.get(date) ?? src.roots.slice(0, 1)
  let md: string | undefined
  let recs: Rec[] = []
  for (const root of roots) {
    md ??= await readText($, `${root}/reports/${date}.md`)
    if (recs.length === 0) {
      const data = (await readJson($, `${root}/reports/${date}.json`)) as any
      if (data && Array.isArray(data.recommendations)) {
        recs = data.recommendations.map((r: any) => ({
          id: String(r?.id ?? ''),
          skill: clean(r?.candidate?.skill),
          problem: clean(r?.problem),
        }))
      }
    }
  }
  return { md, recs }
}

// S5: the ID and the decision are checked before anything is submitted.
async function send($: any, id: string, decision: string, reason?: string): Promise<void> {
  if (!REC_ID.test(id)) return
  if (!DECISIONS.includes(decision)) return
  let args = `${id} ${decision}`
  if (decision === 'reject') {
    const why = clean(reason)
    if (why === '') return
    args += `\n${why}`
  }
  // The engine refuses a prompt that begins with a slash: a command is run
  // with $.command.run, the same as typing `/learn:decide <args>`.
  await $.command.run({ command: 'learn:decide', args })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'cta-reports',
      description: 'Show the CTA learn reports and decide their recommendations',
    })

    return next(e)
  })

  on('command.run', { command: 'cta-reports' }, async $ => {
    await $.ui.open({ id: PANE, title: 'CTA reports' })

    return { text: 'CTA reports pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Input, Select, Markdown } = $.ui.resolve(e)

    const src = await sources($)
    if (!src) {
      return (
        <Box flexDirection="column">
          <Text dimColor>The knowledge base is not configured: set kb in the CTA config.</Text>
        </Box>
      )
    }

    const dates = await listDates($, src)
    if (dates.length === 0) {
      return (
        <Box flexDirection="column">
          <Text dimColor>No reports yet.</Text>
        </Box>
      )
    }
    const pick = await read($, selected)
    const date = dates.includes(pick) ? pick : (dates[0] ?? '')
    const { md, recs } = await loadReport($, src, date)
    const decided = await loadDecisions($, src)
    const typing = await read($, drafts)

    return (
      <Box flexDirection="column">
        <Select
          key="date"
          label="Report"
          options={dates.map(value => ({ value }))}
          value={date}
          onSelect={value => {
            void update($, selected, () => value)
          }}
        />
        {md === undefined ? (
          <Text dimColor>No report text for {date}.</Text>
        ) : (
          <Markdown text={md} />
        )}
        {recs.map(rec => {
          if (!REC_ID.test(rec.id)) {
            return <Text dimColor>A recommendation with an invalid ID is not shown.</Text>
          }
          const row = decided.get(rec.id)
          const title = `${rec.id} ${rec.skill}: ${rec.problem}`
          if (row) {
            return (
              <Box flexDirection="column">
                <Text>{title}</Text>
                <Text dimColor>Decision: {clean(row.decision)}</Text>
                {ISSUE.test(row.issue_url) && <Text dimColor>{clean(row.issue_url)}</Text>}
              </Box>
            )
          }
          const draft = typing[rec.id]
          const isBlank = clean(draft) === ''
          return (
            <Box flexDirection="column">
              <Text>{title}</Text>
              <Box>
                <Button key={`accept:${rec.id}`} onPress={() => send($, rec.id, 'accept')}>
                  Accept
                </Button>
                <Button key={`defer:${rec.id}`} onPress={() => send($, rec.id, 'defer')}>
                  Defer
                </Button>
                <Button
                  key={`reject:${rec.id}`}
                  onPress={() => {
                    void update($, drafts, all => ({ ...all, [rec.id]: all[rec.id] ?? '' }))
                  }}
                >
                  Reject
                </Button>
              </Box>
              {draft !== undefined && (
                <Box>
                  <Input
                    key={`reason:${rec.id}`}
                    placeholder="Why reject?"
                    value={draft}
                    submitLabel="send"
                    onInput={value => {
                      void update($, drafts, all => ({ ...all, [rec.id]: value }))
                    }}
                    onSubmit={value => send($, rec.id, 'reject', value)}
                  />
                  <Button
                    key={`send:${rec.id}`}
                    dimColor={isBlank}
                    onPress={() => (isBlank ? undefined : send($, rec.id, 'reject', draft))}
                  >
                    Send
                  </Button>
                </Box>
              )}
            </Box>
          )
        })}
      </Box>
    )
  })
}
