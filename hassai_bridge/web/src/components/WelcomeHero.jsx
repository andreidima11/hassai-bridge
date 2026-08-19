export function WelcomeHero({ title, hint }) {
  return (
    <div className="welcome-hero relative mx-auto flex w-full max-w-2xl flex-col items-center overflow-visible px-4 py-6 sm:px-8">
      <div className="welcome-fx" aria-hidden="true">
        <div className="welcome-stars" />
        <div className="welcome-glow" />
      </div>
      <h1 className="welcome-title relative z-[1] text-center text-[28px] font-semibold tracking-tight">{title}</h1>
      <p className="welcome-hint relative z-[1] mt-2 max-w-md text-center text-[15px] text-muted-foreground">{hint}</p>
    </div>
  );
}
