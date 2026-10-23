import { alertSourceLabel, bannerText, stateView } from "../lib/format";
import type { Analysis } from "../types";
import { Icon } from "./Icon";

interface Props {
  analysis: Analysis | null;
  holdSeconds: number;
}

/** The biggest element: overall status, the headline, and which part raised the alarm. */
export function StatusBanner({ analysis, holdSeconds }: Props) {
  if (!analysis) {
    return (
      <section className="banner tone-neutral" data-overall="NONE">
        <Icon name="clock" size={56} />
        <div className="banner-text">
          <div className="banner-state">WAITING FOR DATA</div>
          <div className="banner-headline">No rows received yet from the current source.</div>
        </div>
      </section>
    );
  }
  const view = stateView(analysis.overall);
  const text = bannerText(analysis.headline, analysis.device, analysis.alert_source, holdSeconds);
  const chip = alertSourceLabel(analysis.alert_source);
  return (
    <section
      className={`banner tone-${view.tone}`}
      data-overall={analysis.overall}
      data-recovering={text.recovering ? "yes" : "no"}
      aria-live="polite"
    >
      <Icon name={text.recovering ? "clock" : view.icon} size={64} />
      <div className="banner-text">
        <div className="banner-state">
          {view.label}
          {chip && <span className="chip" title="Which part raised the alert">Source: {chip}</span>}
        </div>
        <div className="banner-headline" data-testid="headline">{text.headline}</div>
        {text.detail && <div className="banner-detail">{text.detail}</div>}
      </div>
    </section>
  );
}
