/** The Bellhop mark: a call bell that is also a little robot, with the coral call light on top. */
export function LogoMark({ size = 40, className }: { size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <BotShape />
    </svg>
  )
}

/** The mark's drawing in a 64 unit box, for reuse inside larger illustrations. */
export function BotShape() {
  return (
    <g>
      <circle cx="32" cy="9" r="4.5" fill="#de7456" />
      <rect x="29" y="12" width="6" height="4" rx="1" fill="#43597d" />
      <path d="M32 15C21 15 15.5 23 15.5 33V41C15.5 44 13.5 46 11 47.5H53C50.5 46 48.5 44 48.5 41V33C48.5 23 43 15 32 15Z" fill="#43597d" />
      <rect x="21" y="26" width="22" height="10" rx="5" fill="#e5fafc" />
      <circle cx="27.5" cy="31" r="2.2" fill="#2b3240" />
      <circle cx="36.5" cy="31" r="2.2" fill="#2b3240" />
      <rect x="10" y="47" width="44" height="5" rx="2.5" fill="#2b3240" />
      <circle cx="21" cy="55" r="4.5" fill="#2b3240" />
      <circle cx="43" cy="55" r="4.5" fill="#2b3240" />
      <circle cx="21" cy="55" r="1.6" fill="#e5fafc" />
      <circle cx="43" cy="55" r="1.6" fill="#e5fafc" />
    </g>
  )
}
