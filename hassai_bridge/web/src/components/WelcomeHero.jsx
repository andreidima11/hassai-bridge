export function WelcomeHero({ title, hint }) {
  return (
    <div className="welcome-hero relative mx-auto flex w-full max-w-xl flex-col items-center px-6 py-4">
      <div className="welcome-stars" aria-hidden="true" />
      <div className="welcome-glow" aria-hidden="true" />
      <h1 className="welcome-title relative z-[1] text-center text-[28px] font-semibold tracking-tight">{title}</h1>
      <p className="welcome-hint relative z-[1] mt-2 text-center text-[15px] text-muted-foreground">{hint}</p>
    </div>
  );
}
