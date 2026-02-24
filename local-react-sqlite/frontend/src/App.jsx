import { useEffect, useMemo, useState } from 'react'

const API = 'http://127.0.0.1:8000'

const emptyForm = {
  date: '',
  description: '',
  category: '',
  amount: '',
  verified: false,
  review_note: '',
}

export default function App() {
  const [rows, setRows] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const total = useMemo(
    () => rows.reduce((acc, row) => acc + Number(row.amount || 0), 0).toFixed(2),
    [rows],
  )

  async function loadRows() {
    const res = await fetch(`${API}/transactions`)
    const data = await res.json()
    setRows(data)
  }

  useEffect(() => {
    loadRows().catch(() => setError('Could not load transactions. Start backend first.'))
  }, [])

  async function addRow(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const res = await fetch(`${API}/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const payload = await res.json()
        throw new Error(payload.detail || 'Failed to save')
      }
      setForm(emptyForm)
      await loadRows()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function toggleVerified(row) {
    await fetch(`${API}/transactions/${row.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...row, verified: !row.verified }),
    })
    await loadRows()
  }

  async function removeRow(id) {
    await fetch(`${API}/transactions/${id}`, { method: 'DELETE' })
    await loadRows()
  }

  return (
    <main className="app">
      <h1>CSVEditor Local (React + SQLite)</h1>
      <p className="muted">Transactions are persisted in local-react-sqlite/backend/transactions.db</p>
      {error && <p className="error">{error}</p>}

      <form className="card" onSubmit={addRow}>
        <h2>Add transaction</h2>
        <div className="grid">
          <input placeholder="Date (YYYY/MM/DD)" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} required />
          <input placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required />
          <input placeholder="Category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          <input placeholder="Amount" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} required />
          <label className="checkbox">
            <input type="checkbox" checked={form.verified} onChange={(e) => setForm({ ...form, verified: e.target.checked })} />
            Verified
          </label>
          <input placeholder="Review note" value={form.review_note} onChange={(e) => setForm({ ...form, review_note: e.target.value })} />
        </div>
        <button disabled={saving}>{saving ? 'Saving...' : 'Save transaction'}</button>
      </form>

      <section className="card">
        <h2>Ledger</h2>
        <p><strong>Net total:</strong> {total}</p>
        <table>
          <thead>
            <tr>
              <th>Date</th><th>Description</th><th>Category</th><th>Amount</th><th>Verified</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.date}</td>
                <td>{row.description}</td>
                <td>{row.category}</td>
                <td className={Number(row.amount) < 0 ? 'negative' : 'positive'}>{Number(row.amount).toFixed(2)}</td>
                <td>
                  <button onClick={() => toggleVerified(row)}>{row.verified ? '✅' : '⬜'}</button>
                </td>
                <td>
                  <button className="danger" onClick={() => removeRow(row.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  )
}
