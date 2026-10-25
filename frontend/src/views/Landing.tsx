import { useEffect, useState, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { BotShape, LogoMark } from '../components/Logo'
import { useMode, type Mode } from '../data/mode'
import './landing.css'

// The front door: what Bellhop is, then a way into the real dashboard or the demo home.
// Everything here is copy and illustration; the dashboard itself still reads only the backend.

const GITHUB_URL = 'https://github.com/yashpatolia/calhacks-13'
const DEVPOST_URL = 'https://devpost.com/software/bellhop'

const STEPS = [
  { title: 'A resident presses the bell', text: 'The call shows on the nurse dashboard the moment it rings.' },
  { title: 'The closest free robot goes', text: 'It drives to the room on its own and greets the resident by name.' },
  { title: 'It listens and judges urgency', text: 'Speech to text, a reply from Claude, and an urgency score from 1 to 4, always written in words.' },
  { title: 'It helps, or calls a nurse', text: 'Water, company or a question, the robot handles. A fall, pain or distress goes straight to a nurse.' },
]

const FEATURES: { title: string; text: string; icon: ReactNode; path?: string; cta?: string }[] = [
  { title: 'A live board', text: 'Every open call, most urgent first, with a nurse summary and the whole conversation as it happens.', icon: <IconBoard />, path: '#/live', cta: 'Open the live board' },
  { title: 'Triage you can read', text: 'Emergency, needs a nurse, staff task or robot chat. Urgency is always spelled out, never colour alone.', icon: <IconTriage />, path: '#/live', cta: 'See calls sorted' },
  { title: 'Learns each resident', text: 'Small facts from conversation, each backed by the resident’s own words. Unsure ones wait for a nurse to confirm.', icon: <IconLearn />, path: '#/residents', cta: 'Open a profile' },
  { title: 'Dispatch by hand', text: 'Send any robot to any room, or stop it, from the Dispatch tab.', icon: <IconDispatch />, path: '#/dispatch', cta: 'Send a robot' },
  { title: 'Insights', text: 'Busy hours, repeat callers, mood and pain trends, and the nurse minutes the fleet gave back.', icon: <IconInsights />, path: '#/insights', cta: 'See the trends' },
  { title: 'Grow the fleet', text: 'Add a robot from the Dispatch tab with its own id. It starts taking calls the moment it reports in.', icon: <IconFleet />, path: '#/dispatch', cta: 'Add a robot' },
]

type Level = 1 | 2 | 3 | 4
const LEVEL_WORDS: Record<Level, string> = { 1: 'Robot resolving', 2: 'Staff task', 3: 'Needs a nurse', 4: 'Emergency' }

const BELLS: { ask: string; level: Level; heard: string; steps: string[]; outcome: string }[] = [
  {
    ask: 'Could we chat for a bit?',
    level: 1,
    heard: '"It is quiet today. Could we just talk?"',
    steps: ['The closest free robot rolls to the room', 'It talks about her garden, which it remembers', 'She settles, and the robot closes the call'],
    outcome: 'No nurse needed. The dashboard counts it as nurse time given back.',
  },
  {
    ask: 'Can I have some water?',
    level: 2,
    heard: '"I am so thirsty, could I have some water?"',
    steps: ['The robot checks in and asks what she needs', 'It hands a clear task to an aide: water for room 104', 'The aide brings it; no nurse is pulled away'],
    outcome: 'An aide handles it. The nurse keeps working.',
  },
  {
    ask: 'My hip really hurts',
    level: 3,
    heard: '"My hip has been aching since last night."',
    steps: ['The robot asks how bad, from 0 to 10', 'It writes a nurse summary: hip pain, 6 out of 10', 'A nurse is alerted with the summary and the conversation'],
    outcome: 'The nurse arrives already knowing what is wrong.',
  },
  {
    ask: 'I have fallen',
    level: 4,
    heard: '"I have fallen and I cannot get up."',
    steps: ['A nurse is paged at once, before anything else', 'The robot stays with her and keeps her talking', 'The dashboard puts the call at the very top, marked Emergency'],
    outcome: 'Urgent calls skip the queue. Nothing waits on the robot.',
  },
]

export function Landing() {
  const { setMode } = useMode()
  const still = useReducedMotion()
  const go = (mode: Mode, path = '#/live') => {
    setMode(mode)
    window.location.hash = path
    window.scrollTo(0, 0)
  }
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: still ? 'auto' : 'smooth' })
  const rise = (i: number) => ({
    initial: still ? false : { opacity: 0, y: 18 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.6, delay: 0.1 + i * 0.12, ease: [0.22, 1, 0.36, 1] as const },
  })
  const reveal = {
    initial: still ? false : { opacity: 0, y: 24 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, amount: 0.25 },
    transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] as const },
  }

  return (
    <div className="ld">
      <header className="ld-top">
        <a className="ld-brand" href="#/">
          <LogoMark size={36} />
          Bellhop
        </a>
        <nav className="ld-links" aria-label="On this page">
          <button type="button" onClick={() => scrollTo('how')}>How it works</button>
          <button type="button" onClick={() => scrollTo('try')}>Ring a bell</button>
          <button type="button" onClick={() => scrollTo('features')}>Features</button>
          <button type="button" onClick={() => scrollTo('learning')}>Learning</button>
        </nav>
        <button type="button" className="ld-btn small" onClick={() => go('live')}>
          Dashboard
        </button>
      </header>

      <section className="ld-hero">
        <div className="ld-hero-copy">
          <motion.p className="ld-badge" {...rise(0)}>
            <img src="/calhacks-13.svg" alt="Cal Hacks 13.0 logo" width="65" height="44" /> Built at Cal Hacks 13.0
          </motion.p>
          <motion.p className="ld-eyebrow" {...rise(0)}>An autonomous fleet for care homes</motion.p>
          <motion.h1 {...rise(1)}>
            The call bell, answered.
            <em>Nurses saved for the moments that need them.</em>
          </motion.h1>
          <motion.p className="ld-lede" {...rise(2)}>
            Most call bells are not emergencies. A drink, a chat, a question about lunch. Bellhop sends a small robot from its fleet to answer them, and calls a nurse straight away when something is urgent, so nursing time goes where it is needed.
          </motion.p>
          <motion.div className="ld-actions" {...rise(3)}>
            <button type="button" className="ld-btn primary" onClick={() => go('live')}>
              Open the dashboard
            </button>
            <button type="button" className="ld-btn demo" onClick={() => go('demo')}>
              Try the demo
            </button>
          </motion.div>
          <motion.p className="ld-note" {...rise(4)}>
            The demo is a made-up care home with bells ringing live. It never touches your real home.
          </motion.p>
        </div>
        <motion.div className="ld-scene-wrap" {...rise(2)}>
          <Corridor />
        </motion.div>
      </section>

      <section id="how" className="ld-section">
        <motion.h2 {...reveal}>How a bell press goes</motion.h2>
        <ol className="ld-steps">
          {STEPS.map((s, i) => (
            <motion.li key={s.title} {...reveal} transition={{ ...reveal.transition, delay: i * 0.1 }}>
              <span className="ld-step-n">{i + 1}</span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </motion.li>
          ))}
        </ol>
      </section>

      <section id="try" className="ld-section">
        <motion.h2 {...reveal}>Try it: ring a bell</motion.h2>
        <motion.p className="ld-sub" {...reveal}>Pick what the resident says. See who answers, and how fast a nurse hears about it.</motion.p>
        <motion.div {...reveal}>
          <TriagePicker />
        </motion.div>
      </section>

      <section id="features" className="ld-section">
        <motion.h2 {...reveal}>Everything a nurse needs to see</motion.h2>
        <div className="ld-features">
          {FEATURES.map((f, i) => (
            <motion.article key={f.title} className="ld-feature" {...reveal} transition={{ ...reveal.transition, delay: (i % 3) * 0.08 }}>
              <span className="ld-icon">{f.icon}</span>
              <h3>{f.title}</h3>
              <p>{f.text}</p>
              {f.path && (
                <button type="button" className="ld-feature-go" onClick={() => go('demo', f.path)}>
                  {f.cta} in the demo <span aria-hidden="true">&rarr;</span>
                </button>
              )}
            </motion.article>
          ))}
        </div>
      </section>

      <section id="learning" className="ld-section ld-learning">
        <motion.div className="ld-learning-copy" {...reveal}>
          <h2>It learns, then it remembers</h2>
          <p>
            When a conversation ends, Bellhop writes down what it picked up, right in the conversation. A fact is only kept when the resident said it in their own words, and anything about health waits for a nurse to confirm.
          </p>
          <p>
            The next time she rings, the robot already knows her. It offers the tea she likes, and the nurse sees what matters before walking in.
          </p>
          <button type="button" className="ld-btn demo" onClick={() => go('demo', '#/residents')}>
            See what it has learned
          </button>
        </motion.div>
        <motion.div {...reveal} transition={{ ...reveal.transition, delay: 0.12 }}>
          <LearnStory />
        </motion.div>
      </section>

      <motion.section className="ld-cta" {...reveal}>
        <h2>See it working</h2>
        <p>Open the dashboard for your home, or step into the demo and watch the fleet handle a busy evening.</p>
        <div className="ld-actions">
          <button type="button" className="ld-btn primary" onClick={() => go('live')}>
            Open the dashboard
          </button>
          <button type="button" className="ld-btn demo" onClick={() => go('demo')}>
            Try the demo
          </button>
        </div>
      </motion.section>

      <footer className="ld-foot">
        <span className="ld-brand small">
          <LogoMark size={24} />
          Bellhop
        </span>
        <span>Robots handle the routine. Nurses handle the care.</span>
        <span className="ld-foot-links">
          Built at Cal Hacks 13.0
          <a href={DEVPOST_URL} target="_blank" rel="noreferrer">
            Devpost
          </a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">
            GitHub
          </a>
        </span>
      </footer>
    </div>
  )
}

/** Pick what the resident says; the card plays out who answers and what the nurse sees. */
function TriagePicker() {
  const [pick, setPick] = useState(0)
  const still = useReducedMotion()
  const bell = BELLS[pick]
  const appear = (delay: number) => ({
    initial: still ? false : { opacity: 0, x: -10 },
    animate: { opacity: 1, x: 0 },
    transition: { duration: 0.35, delay },
  })
  return (
    <div className="ld-triage">
      <div className="ld-asks" role="radiogroup" aria-label="What the resident says">
        {BELLS.map((b, i) => (
          <button key={b.ask} type="button" role="radio" aria-checked={i === pick} className={`ld-ask l${b.level}`} onClick={() => setPick(i)}>
            <BellIcon />
            <span>
              <b>"{b.ask}"</b>
              <small>{LEVEL_WORDS[b.level]}</small>
            </span>
          </button>
        ))}
      </div>
      <AnimatePresence mode="wait">
        <motion.div
          key={pick}
          className={`ld-outcome l${bell.level}`}
          aria-live="polite"
          initial={still ? false : { opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={still ? undefined : { opacity: 0, y: -8 }}
          transition={{ duration: 0.3 }}
        >
          <div className="ld-outcome-head">
            <span className={`ld-chip l${bell.level}`}>
              {bell.level === 4 && <i className="ld-pulse" aria-hidden="true" />}
              Urgency {bell.level} of 4: {LEVEL_WORDS[bell.level]}
            </span>
            <span className="ld-room">Room 104, Margaret</span>
          </div>
          <p className="ld-heard">{bell.heard}</p>
          <ol className="ld-flow">
            {bell.steps.map((s, i) => (
              <motion.li key={s} {...appear(0.2 + i * 0.3)}>
                <span>{i + 1}</span>
                {s}
              </motion.li>
            ))}
          </ol>
          <motion.p className="ld-result" {...appear(0.2 + bell.steps.length * 0.3)}>
            {bell.outcome}
          </motion.p>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

/** Two days in Margaret's week: what Bellhop learns on Tuesday, and how it uses it on Friday. */
function LearnStory() {
  const [day, setDay] = useState(0)
  const [auto, setAuto] = useState(true)
  const still = useReducedMotion()
  useEffect(() => {
    if (!auto || still) return
    const t = setInterval(() => setDay((d) => 1 - d), 9000)
    return () => clearInterval(t)
  }, [auto, still])
  const choose = (d: number) => {
    setAuto(false)
    setDay(d)
  }
  const line = (i: number) => ({
    initial: still ? false : { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.35, delay: 0.1 + i * 0.35 },
  })
  return (
    <figure className="ld-talk">
      <div className="ld-days" role="tablist" aria-label="Example conversations">
        {['Tuesday: it learns', 'Friday: it remembers'].map((label, i) => (
          <button key={label} type="button" role="tab" aria-selected={day === i} onClick={() => choose(i)}>
            {label}
          </button>
        ))}
      </div>
      <AnimatePresence mode="wait">
        <motion.div key={day} className="ld-day" initial={still ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={still ? undefined : { opacity: 0 }} transition={{ duration: 0.25 }}>
          {day === 0 ? (
            <>
              <motion.p className="resident" {...line(0)}><span>Margaret</span>Could you stay a minute? I like a hot cup of tea with honey in the afternoon.</motion.p>
              <motion.p className="robot" {...line(1)}><span>Bellhop</span>Of course. Hot tea with honey sounds lovely. I will remember that.</motion.p>
              <motion.p className="resident" {...line(2)}><span>Margaret</span>It takes my breath going to the bathroom these days.</motion.p>
              <motion.p className="learned saved" {...line(3)}><span>Bellhop</span><b>Learned about Margaret:</b> Likes a hot cup of tea with honey in the afternoon<em>Saved to her profile</em></motion.p>
              <motion.p className="learned pending" {...line(4)}><span>Bellhop</span><b>Learned about Margaret:</b> Gets breathless walking to the bathroom<em>Waiting for a nurse to confirm</em></motion.p>
            </>
          ) : (
            <>
              <motion.p className="resident" {...line(0)}><span>Margaret</span>Could you bring me something to drink?</motion.p>
              <motion.p className="robot" {...line(1)}>
                <span>Bellhop</span>Of course, Margaret. A hot cup of tea with honey, like you have in the afternoons?
                <small className="ld-used">Remembered from Tuesday</small>
              </motion.p>
              <motion.p className="resident" {...line(2)}><span>Margaret</span>Oh, you remembered. Yes please.</motion.p>
              <motion.div className="ld-nurse" {...line(3)}>
                <span>On the nurse&rsquo;s screen</span>
                <b>Room 104, Margaret Alvarez: tea, staff task</b>
                <p>
                  <strong>What Bellhop knows.</strong> Likes a hot cup of tea with honey in the afternoon. Gets breathless walking to the bathroom, confirmed by a nurse on Tuesday.
                </p>
              </motion.div>
            </>
          )}
        </motion.div>
      </AnimatePresence>
    </figure>
  )
}

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </svg>
  )
}

/** A corridor of rooms: a bell lights up, a robot rolls over, talks, and the call is handled. Loops gently. */
function Corridor() {
  const rooms = ['101', '102', '103', '104', '105']
  return (
    <svg className="ld-scene" viewBox="0 0 720 320" role="img" aria-label="A call light comes on above room 104, a Bellhop robot rolls to the door, talks with the resident, and the call is marked handled.">
      <rect x="0" y="0" width="720" height="320" rx="18" className="ld-wall" />
      <rect x="0" y="262" width="720" height="58" className="ld-floor" />
      {rooms.map((n, i) => {
        const x = 40 + i * 140
        const active = n === '104'
        return (
          <g key={n}>
            <rect x={x} y="100" width="96" height="162" rx="6" className="ld-door" />
            <circle cx={x + 80} cy="185" r="4" className="ld-knob" />
            <text x={x + 48} y="128" textAnchor="middle" className="ld-plate">{n}</text>
            {active ? (
              <>
                <circle cx={x + 48} cy="74" r="20" className="ld-ring" />
                <circle cx={x + 48} cy="74" r="10" className="ld-light active" />
              </>
            ) : (
              <circle cx={x + 48} cy="74" r="10" className="ld-light" />
            )}
          </g>
        )
      })}
      <g className="ld-bubble">
        <rect x="372" y="138" width="260" height="46" rx="12" />
        <path d="M494 184 L504 197 L512 184 Z" />
        <text x="502" y="166" textAnchor="middle">Hello Margaret, what can I get you?</text>
      </g>
      <g className="ld-handled">
        <rect x="414" y="18" width="188" height="30" rx="15" />
        <text x="508" y="38" textAnchor="middle">Handled by Bellhop</text>
      </g>
      <g className="ld-bot">
        <g transform="translate(28 190) scale(1.3)">
          <BotShape />
        </g>
      </g>
    </svg>
  )
}

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  )
}
function IconBoard() {
  return <Icon><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M9 9v11" /></Icon>
}
function IconTriage() {
  return <Icon><path d="M12 3l9 16H3z" /><path d="M12 10v4M12 17h.01" /></Icon>
}
function IconLearn() {
  return <Icon><path d="M4 5h11a3 3 0 0 1 3 3v11H7a3 3 0 0 1-3-3z" /><path d="M8 9h6M8 13h4" /></Icon>
}
function IconDispatch() {
  return <Icon><circle cx="12" cy="10" r="3" /><path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z" /></Icon>
}
function IconInsights() {
  return <Icon><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Icon>
}
function IconFleet() {
  return <Icon><rect x="4" y="8" width="11" height="9" rx="3" /><path d="M9.5 8V5" /><circle cx="9.5" cy="4" r="1" /><circle cx="7.5" cy="12.5" r="0.6" /><circle cx="11.5" cy="12.5" r="0.6" /><path d="M7 20h5M19 9v6M16 12h6" /></Icon>
}
