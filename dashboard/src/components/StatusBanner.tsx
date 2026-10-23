import { alertSourceLabel, bannerText, stateView, type Tone } from "../lib/format";
import type { Analysis } from "../types";
import { Icon } from "./Icon";

interface Props {
  analysis: Analysis | null;
  holdSeconds: number;
}

/** The overall status: calm and neutral when normal, tinted with a status bar for a
 *  warning, a solid (not neon) red for critical. */
export function StatusBanner({ analysis, holdSeconds }: Props) {
  if (!analysis) {
    return (
      <section className="banner" data-tone="neutral" data-overall="NONE">
        <Icon name="clock" size={32} className="banner-icon" />
        <div className="banner-text">
          <div className="banner-state">Waiting for data</div>
          <div className="banner-headline">No rows received yet from the current source</div>
        </div>
      </section>
    );
  }
  const view = stateView(analysis.overall);
  const text = bannerText(analysis.headline, analysis.device, analysis.alert_source, holdSeconds);
  const source = alertSourceLabel(analysis.alert_source);
  // A warning raised by ML alone gets the ML colour, so it reads differently from a rule limit.
  const tone: Tone = analysis.overall === "WARNING" && analysis.alert_source === "ml" ? "ml" : view.tone;
  return (
    <section
      className="banner"
      data-tone={tone}
      data-overall={analysis.overall}
      data-recovering={text.recovering ? "yes" : "no"}
      aria-live="polite"
    >
      <Icon name={text.recovering ? "clock" : view.icon} size={32} className="banner-icon" />
      <div className="banner-text">
        <div className="banner-state">
          {view.label}
          {source && <span className="banner-source" title="Which part raised the alert">· raised by {source}</span>}
        </div>
        <div className="banner-headline" data-testid="headline">{text.headline}</div>
        {text.detail && <div className="banner-detail" data-testid="headline-detail">{text.detail}</div>}
      </div>
    </section>
  );
}
