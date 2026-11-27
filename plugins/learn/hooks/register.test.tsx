import { expect, test } from 'claude-code/testing'

const HOME = '/home/tester'
const KB = '/kb'
const LOCAL = `${HOME}/.local/share/cta/learn`
const PANE = {
  plugin: 'learn',
  component: 'Pane',
  requestId: 'cta-reports',
  surface: 'desktop',
  props: {
    title: 'CTA reports',
    isFocused: false,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

type Files = Record<string, string>

// Stands for the engine beneath the mod: a tiny file system and environment.
function seed(on: any, files: Files, dirs: Record<string, string[]> = {}) {
  on('env.get', (_: any, e: any) => ({ value: e.name === 'HOME' ? HOME : undefined }))
  on('fs.read', (_: any, e: any) => {
    if (!(e.path in files)) throw new Error('ENOENT')
    return { value: files[e.path] }
  })
  on('fs.list', (_: any, e: any) => {
    if (!(e.path in dirs)) throw new Error('ENOENT')
    return { value: (dirs[e.path] ?? []).map(name => ({ name, kind: 'dir', size: 0, mtimeMs: 0, isLink: false })) }
  })
  on('fs.exists', (_: any, e: any) => ({ value: e.path in files }))
}

const DATES = [
  '2026-11-30', '2026-11-23', '2026-11-16', '2026-11-09',
  '2026-11-02', '2026-10-26', '2026-10-19',
]
const index = (dates: string[]) =>
  JSON.stringify(dates.map(date => ({ date, status: 'green', headline: `h ${date}` })))

const rec = (id: string, skill: string) => ({
  id,
  candidate: {
    skill, signal: 'failures', fingerprint: `${skill}|failures`, metric: 'fail',
    value: 0.4, threshold: 0.2, sessions: 4, evidence: [], panel: '',
  },
  problem: `problem of ${skill}`, why: '', change: '', measure: '',
})

const report = (date: string, recs: ReturnType<typeof rec>[]) =>
  JSON.stringify({ date, status: 'green', headline: 'h', recommendations: recs })

function base(extra: Files = {}): Files {
  return {
    [`${HOME}/.config/cta/config.toml`]: `kb = "${KB}"\n`,
    [`${LOCAL}/reports/index.json`]: index(DATES),
    [`${LOCAL}/reports/2026-11-30.md`]: '# Report of the week',
    [`${LOCAL}/reports/2026-11-30.json`]: report('2026-11-30', [
      rec('2026-11-30-R1', 'alpha'),
      rec('2026-11-30-R2', 'beta'),
    ]),
    ...extra,
  }
}

function submits(on: any): string[] {
  const sent: string[] = []
  // The engine refuses a prompt that starts with "/", so a decision is a
  // command run: `/learn:decide <args>`.
  on('command.run', (_: any, e: any) => {
    sent.push(`/${e.command} ${e.args}`)
    return {}
  })
  return sent
}

test('the Select lists the 5 newest dates of 7', async ($, on) => {
  seed(on, base())
  const ui = await $.ui.mount(PANE)

  const select = await ui.find({ type: 'Select' })
  const options = select?.props.options as { value: string }[]
  expect(options.map(o => o.value)).toEqual(DATES.slice(0, 5))
  await ui.unmount()
})

test('an index entry that is not a date is not listed', async ($, on) => {
  seed(on, base({
    [`${LOCAL}/reports/index.json`]: index(['../../x', '2026-11-30', '2026-11-3x']),
  }))
  const ui = await $.ui.mount(PANE)

  const select = await ui.find({ type: 'Select' })
  const options = select?.props.options as { value: string }[]
  expect(options.map(o => o.value)).toEqual(['2026-11-30'])
  await ui.unmount()
})

test('an undecided recommendation shows three buttons', async ($, on) => {
  seed(on, base())
  const ui = await $.ui.mount(PANE)

  for (const id of ['2026-11-30-R1', '2026-11-30-R2']) {
    for (const verb of ['accept', 'defer', 'reject']) {
      expect(await ui.find({ type: 'Button', key: `${verb}:${id}` })).toBeDefined()
    }
  }
  await ui.unmount()
})

test('a decided recommendation shows its decision and no buttons', async ($, on) => {
  seed(on, base({
    [`${LOCAL}/decisions.jsonl`]: [
      JSON.stringify({ id: '2026-11-30-R1', decision: 'accept', issue_url: 'https://github.com/o/r/issues/3', reason: '', date: '2026-11-30' }),
      'not json',
    ].join('\n'),
  }))
  const ui = await $.ui.mount(PANE)

  expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-R1' })).toBeUndefined()
  expect(await ui.find({ type: 'Button', key: 'reject:2026-11-30-R1' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /accept/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /github\.com\/o\/r\/issues\/3/ })).toBeDefined()
  expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-R2' })).toBeDefined()
  await ui.unmount()
})

test('an issue link that is not github is not shown', async ($, on) => {
  seed(on, base({
    [`${LOCAL}/decisions.jsonl`]: JSON.stringify({ id: '2026-11-30-R1', decision: 'accept', issue_url: 'https://evil.example/x', reason: '' }),
  }))
  const ui = await $.ui.mount(PANE)

  expect(await ui.find({ type: 'Text', text: /evil\.example/ })).toBeUndefined()
  await ui.unmount()
})

test('Accept submits the decide command', async ($, on) => {
  seed(on, base())
  const sent = submits(on)
  const ui = await $.ui.mount(PANE)

  await ui.press({ key: 'accept:2026-11-30-R2' })
  await ui.press({ key: 'defer:2026-11-30-R1' })

  expect(sent).toEqual([
    '/learn:decide 2026-11-30-R2 accept',
    '/learn:decide 2026-11-30-R1 defer',
  ])
  await ui.unmount()
})

test('Reject reveals an Input; Send is disabled while blank, then submits', async ($, on) => {
  seed(on, base())
  const sent = submits(on)
  const ui = await $.ui.mount(PANE)

  expect(await ui.find({ type: 'Input', key: 'reason:2026-11-30-R1' })).toBeUndefined()
  await ui.press({ key: 'reject:2026-11-30-R1' })
  expect(await ui.find({ type: 'Input', key: 'reason:2026-11-30-R1' })).toBeDefined()
  const send = await ui.find({ type: 'Button', key: 'send:2026-11-30-R1' })
  expect(send?.props.dimColor).toBe(true)

  await ui.input({ key: 'reason:2026-11-30-R1', text: '   ', kind: 'change' })
  expect((await ui.find({ key: 'send:2026-11-30-R1' }))?.props.dimColor).toBe(true)
  await ui.press({ key: 'send:2026-11-30-R1' })
  expect(sent).toEqual([])

  await ui.input({ key: 'reason:2026-11-30-R1', text: 'too noisy\n', kind: 'change' })
  expect((await ui.find({ key: 'send:2026-11-30-R1' }))?.props.dimColor).toBeFalsy()
  await ui.press({ key: 'send:2026-11-30-R1' })

  expect(sent).toEqual(['/learn:decide 2026-11-30-R1 reject\ntoo noisy'])
  await ui.unmount()
})

test('a recommendation ID that is not valid never reaches submit', async ($, on) => {
  seed(on, base({
    [`${LOCAL}/reports/2026-11-30.json`]: report('2026-11-30', [
      rec('2026-11-30-R1; rm -rf', 'alpha'),
    ]),
  }))
  const sent = submits(on)
  const ui = await $.ui.mount(PANE)

  expect(await ui.find({ type: 'Button', text: /Accept/ })).toBeUndefined()
  expect(sent).toEqual([])
  await ui.unmount()
})

test('lists the last 5 reports from reports_dir', async ($, on) => {
  seed(on, base({ [`${LOCAL}/reports/index.json`]: index(DATES.slice(0, 6)) }))
  const ui = await $.ui.mount(PANE)

  const options = (await ui.find({ type: 'Select' }))?.props.options as { value: string }[]
  expect(options.map(o => o.value)).toEqual(DATES.slice(0, 5))
  await ui.unmount()
})

async function reportsDirOptions($: any, on: any, quoted: string, extra: Files = {}) {
  seed(on, base({
    [`${HOME}/.config/cta/config.toml`]: `kb = "${KB}"\n[learn]\nreports_dir = ${quoted}\n`,
    [`${HOME}/r/reports/index.json`]: index(['2026-11-30']),
    ...extra,
  }))
  const ui = await $.ui.mount(PANE)
  const options = (await ui.find({ type: 'Select' }))?.props.options as { value: string }[]
  await ui.unmount()
  return options.map(o => o.value)
}

test('parses reports_dir quoted either way', async ($, on) => {
  expect(await reportsDirOptions($, on, `'~/r'  # c`)).toEqual(['2026-11-30'])
})

test('parses reports_dir in double quotes', async ($, on) => {
  expect(await reportsDirOptions($, on, `"~/r"`)).toEqual(['2026-11-30'])
})

test('a relative reports_dir falls back to the default folder', async ($, on) => {
  expect(await reportsDirOptions($, on, `"rel"`)).toEqual(DATES.slice(0, 5))
})

test('a climbing reports_dir falls back to the default folder', async ($, on) => {
  expect(await reportsDirOptions($, on, `"~/../x"`)).toEqual(DATES.slice(0, 5))
})

test('pane ignores old report worktree', async ($, on) => {
  const WT = `${HOME}/.local/share/cta/kb-worktrees`
  seed(
    on,
    base({
      [`${LOCAL}/reports/index.json`]: index(['2026-11-23']),
      [`${WT}/learn-report-2026-11-30/learn/reports/index.json`]: index(['2026-11-30']),
      [`${WT}/learn-report-2026-11-30/learn/reports/2026-11-30.md`]: '# Fresh report',
    }),
    { [WT]: ['learn-report-2026-11-30', 'learn-decisions'] },
  )
  const ui = await $.ui.mount(PANE)

  const options = (await ui.find({ type: 'Select' }))?.props.options as { value: string }[]
  expect(options.map(o => o.value)).toEqual(['2026-11-23'])
  await ui.unmount()
})

test('without kb the reports still list and decisions are empty', async ($, on) => {
  seed(on, base({ [`${HOME}/.config/cta/config.toml`]: '[learn]\n' }))
  const ui = await $.ui.mount(PANE)

  const options = (await ui.find({ type: 'Select' }))?.props.options as { value: string }[]
  expect(options.map(o => o.value)).toEqual(DATES.slice(0, 5))
  expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-R1' })).toBeDefined()
  await ui.unmount()
})

// Rot audit: items come from the report JSON, decisions from the one local file.
const rot = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  location: `plugins/x/${id}`,
  problem: `problem ${id}`,
  fix: `fix ${id}`,
  fingerprint: `fp|${id}`,
  accept: true,
  repo: 'owner/repo',
  ...over,
})

const withRot = (items: Record<string, unknown>[], kind = 'broken', md = '# Report of the week') =>
  base({
    [`${LOCAL}/reports/2026-11-30.md`]: md,
    [`${LOCAL}/reports/2026-11-30.json`]: JSON.stringify({
      date: '2026-11-30',
      status: 'green',
      headline: 'h',
      recommendations: [],
      rot: { broken: [], stale: [], permission: [], [kind]: items },
    }),
  })

for (const surface of ['terminal', 'desktop'] as const) {
  const pane = { ...PANE, surface } as any

  test(`${surface}: decisions are read from decisions.jsonl in reports_dir`, async ($, on) => {
    seed(on, base({
      [`${LOCAL}/decisions.jsonl`]: JSON.stringify({ id: '2026-11-30-R1', decision: 'accept', issue_url: '' }),
      [`${KB}/learn/decisions.jsonl`]: JSON.stringify({ id: '2026-11-30-R2', decision: 'accept', issue_url: '' }),
    }))
    const ui = await $.ui.mount(pane)

    expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-R1' })).toBeUndefined()
    expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-R2' })).toBeDefined()
    await ui.unmount()
  })

  test(`${surface}: a rot item shows Accept and Dismiss; a connector shows Dismiss only`, async ($, on) => {
    seed(on, withRot([
      rot('2026-11-30-B1'),
      rot('2026-11-30-B2', { accept: false }),
    ]))
    const ui = await $.ui.mount(pane)

    expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-B1' })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: 'reject:2026-11-30-B1' })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-B2' })).toBeUndefined()
    expect(await ui.find({ type: 'Button', key: 'reject:2026-11-30-B2' })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: 'defer:2026-11-30-B1' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /Rot audit/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /problem 2026-11-30-B1/ })).toBeDefined()
    await ui.unmount()
  })

  test(`${surface}: Accept on a rot item runs learn:decide`, async ($, on) => {
    seed(on, withRot([rot('2026-11-30-S1')], 'stale'))
    const sent = submits(on)
    const ui = await $.ui.mount(pane)

    await ui.press({ key: 'accept:2026-11-30-S1' })

    expect(sent).toEqual(['/learn:decide 2026-11-30-S1 accept'])
    await ui.unmount()
  })

  test(`${surface}: Dismiss opens the reason box and Send runs reject with the reason`, async ($, on) => {
    seed(on, withRot([rot('2026-11-30-P1')], 'permission'))
    const sent = submits(on)
    const ui = await $.ui.mount(pane)

    expect(await ui.find({ type: 'Input', key: 'reason:2026-11-30-P1' })).toBeUndefined()
    await ui.press({ key: 'reject:2026-11-30-P1' })
    expect(await ui.find({ type: 'Input', key: 'reason:2026-11-30-P1' })).toBeDefined()
    await ui.input({ key: 'reason:2026-11-30-P1', text: 'not a problem\n', kind: 'change' })
    await ui.press({ key: 'send:2026-11-30-P1' })

    expect(sent).toEqual(['/learn:decide 2026-11-30-P1 reject\nnot a problem'])
    await ui.unmount()
  })

  test(`${surface}: a decided rot item shows its decision and issue link, no buttons`, async ($, on) => {
    seed(on, {
      ...withRot([rot('2026-11-30-B1'), rot('2026-11-30-B2')]),
      [`${LOCAL}/decisions.jsonl`]: JSON.stringify({
        id: '2026-11-30-B1', decision: 'accept', issue_url: 'https://github.com/o/r/issues/9',
      }),
    })
    const ui = await $.ui.mount(pane)

    expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-B1' })).toBeUndefined()
    expect(await ui.find({ type: 'Button', key: 'reject:2026-11-30-B1' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /accept/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /issues\/9/ })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: 'accept:2026-11-30-B2' })).toBeDefined()
    await ui.unmount()
  })

  test(`${surface}: a rot item without an ID (an old report) shows no buttons`, async ($, on) => {
    const old = { location: 'a/b', problem: 'old problem', fix: 'old fix' }
    seed(on, withRot([old, old]))
    const sent = submits(on)
    const ui = await $.ui.mount(pane)

    expect(await ui.find({ type: 'Text', text: /old problem/ })).toBeDefined()
    expect(await ui.find({ type: 'Button', text: /Accept|Dismiss/ })).toBeUndefined()
    expect(sent).toEqual([])
    await ui.unmount()
  })

  test(`${surface}: a rot ID that is not valid shows no buttons`, async ($, on) => {
    seed(on, withRot([rot('2026-11-30-B1; reboot')]))
    const ui = await $.ui.mount(pane)

    expect(await ui.find({ type: 'Button', text: /Accept|Dismiss/ })).toBeUndefined()
    await ui.unmount()
  })

  test(`${surface}: 40 rot items all draw, each with a unique key`, async ($, on) => {
    const items = Array.from({ length: 40 }, (_, i) => rot(`2026-11-30-B${i + 1}`))
    seed(on, withRot(items))
    const ui = await $.ui.mount(pane)

    for (let i = 1; i <= 40; i++) {
      expect(await ui.find({ key: `rot:2026-11-30-B${i}` })).toBeDefined()
      expect(await ui.find({ type: 'Button', key: `accept:2026-11-30-B${i}` })).toBeDefined()
    }
    await ui.unmount()
  })

  test(`${surface}: the markdown is drawn without its Rot audit section`, async ($, on) => {
    const md = '# Week\n\nintro\n\n## Rot audit\n\n- RAWROT item\n\n## Next\n\nafter'
    seed(on, withRot([rot('2026-11-30-B1')], 'broken', md))
    const ui = await $.ui.mount(pane)

    const text = String((await ui.find({ type: 'Markdown' }))?.props.text)
    expect(text).not.toMatch(/Rot audit|RAWROT/)
    expect(text).toMatch(/intro/)
    expect(text).toMatch(/## Next/)
    await ui.unmount()
  })
}
