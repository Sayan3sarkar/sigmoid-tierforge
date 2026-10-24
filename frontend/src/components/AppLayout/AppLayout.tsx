import { Anchor, AppShell, Container, Group, Title } from '@mantine/core'
import { NavLink, Outlet } from 'react-router'

import classes from './AppLayout.module.css'

const LINKS = [
  { to: '/jobs', label: 'Jobs' },
  { to: '/upload', label: 'Upload' },
]

/** Page frame: header with navigation, and the current page below it. */
export function AppLayout() {
  return (
    <AppShell header={{ height: 60 }} padding="md">
      <AppShell.Header>
        <Container size="xl" className={classes.header}>
          <Title order={3}>TierForge</Title>
          <Group gap="lg" component="nav">
            {LINKS.map((link) => (
              <Anchor
                key={link.to}
                component={NavLink}
                to={link.to}
                className={classes.link}
                underline="never"
              >
                {link.label}
              </Anchor>
            ))}
          </Group>
        </Container>
      </AppShell.Header>
      <AppShell.Main>
        <Container size="xl">
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  )
}
