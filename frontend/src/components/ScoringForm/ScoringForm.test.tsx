import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/errors'
import { SCORING_CONFIG } from '@/test/fixtures'
import { renderWithProviders } from '@/test/render'

import { ScoringForm } from './ScoringForm'

async function setValue(label: string, index: number, value: string) {
  const input = screen.getAllByLabelText(label)[index]
  await userEvent.clear(input)
  await userEvent.type(input, value)
}

describe('ScoringForm', () => {
  it('submits the settings', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    renderWithProviders(<ScoringForm initialConfig={SCORING_CONFIG} onSubmit={onSubmit} />)

    await userEvent.click(screen.getByRole('button', { name: 'Score stores' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(SCORING_CONFIG))
  })

  it('blocks weights that don’t add up to 100, without calling the API', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    renderWithProviders(<ScoringForm initialConfig={SCORING_CONFIG} onSubmit={onSubmit} />)

    await setValue('Weight', 2, '30') // size_sqft: 20 → 30, total 110
    await userEvent.click(screen.getByRole('button', { name: 'Score stores' }))

    expect(await screen.findByText('Weights must add up to 100, not 110')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Weights total: 110 / 100')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('blocks Medium above Large', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    renderWithProviders(<ScoringForm initialConfig={SCORING_CONFIG} onSubmit={onSubmit} />)

    await setValue('Medium from', 0, '80')
    await userEvent.click(screen.getByRole('button', { name: 'Score stores' }))

    expect(await screen.findByText('Medium (80) must not be above Large (70)')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('shows the API’s field errors next to their inputs', async () => {
    const error = new ApiError(422, 'Invalid request.', [
      { field: 'bars.revenue', message: 'Revenue bar rejected by the API' },
    ])
    const onSubmit = vi.fn().mockRejectedValue(error)
    renderWithProviders(
      <ScoringForm initialConfig={SCORING_CONFIG} onSubmit={onSubmit} serverError={error} />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Score stores' }))

    expect(await screen.findByText('Revenue bar rejected by the API')).toBeInTheDocument()
    // Shown on the input, so not repeated in the alert's list.
    expect(screen.getByRole('alert')).not.toHaveTextContent('bars.revenue')
  })
})
