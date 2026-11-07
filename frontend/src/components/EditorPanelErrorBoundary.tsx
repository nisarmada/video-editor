import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  /** Shown in the message, e.g. "Player" or "Timeline" */
  name: string;
  children: ReactNode;
};

type State = {
  error: Error | null;
};

/**
 * Isolates panel failures so one broken subtree does not blank the whole editor.
 */
export default class EditorPanelErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`[panel:${this.props.name}]`, error.message, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="panel-error-boundary" role="alert">
          <p className="panel-error-boundary__text">
            <strong>{this.props.name}</strong> crashed:{" "}
            {this.state.error.message || "Unknown error"}
          </p>
          <button
            type="button"
            className="btn panel-error-boundary__retry"
            onClick={() => this.setState({ error: null })}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
