import { Component } from 'react';
import i18n from '../i18n';

/** Catches render errors in a subtree and shows a one-line fallback. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() { return { hasError: true }; }

  componentDidCatch(error, info) {
    console.error(`[ErrorBoundary] ${this.props.label ?? 'component'} crashed:`, error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return <div className="boundary">{i18n.t('error.component_failed', { name: this.props.label ?? 'Component' })}</div>;
    }
    return this.props.children;
  }
}
