import React from 'react'
import ErrorPage from '../pages/ErrorPage'

// Top-level React error boundary — wraps <App/> in main.jsx. Catches any
// uncaught render-time exception anywhere in the tree and shows the
// generic ErrorPage instead of a blank/broken page. Existing per-page
// try/catch error handling (form submissions, API calls) is unaffected —
// this only catches render exceptions those try/catch blocks can't.
export default class ErrorBoundary extends React.Component {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    console.error('Uncaught render error:', error, info)
  }

  render() {
    if (this.state.hasError) return <ErrorPage />
    return this.props.children
  }
}
