import { RecommendationChips } from "./RecommendationChips.jsx";

export function WelcomeHero({ title, hint, recommendations, onPickRecommendation }) {
  return (
    <div className="welcome-hero relative mx-auto flex w-full max-w-2xl flex-col items-center px-4 py-6 sm:px-8">
      <h1 className="welcome-title text-center text-[28px] font-semibold tracking-tight">{title}</h1>
      <p className="welcome-hint mt-2 max-w-md text-center text-[15px] text-muted-foreground">{hint}</p>
      {recommendations?.length ? (
        <div className="pointer-events-auto mt-6 w-full max-w-xl">
          <RecommendationChips
            items={recommendations}
            onSelect={onPickRecommendation}
            variant="empty"
          />
        </div>
      ) : null}
    </div>
  );
}
