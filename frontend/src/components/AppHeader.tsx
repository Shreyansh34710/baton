export function AppHeader() {
  return (
    <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <a className="flex items-center gap-3" href="/" aria-label="BATON home">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-cyan-400 font-black text-slate-950">B</span>
          <span className="text-sm font-bold tracking-[0.2em] text-slate-100">BATON</span>
        </a>
        <span className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-200">
          Project handover
        </span>
      </div>
    </header>
  );
}
