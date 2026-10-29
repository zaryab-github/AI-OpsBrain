import { LogOut, Menu, Moon, Sun, UserCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { BRAND_ICON, visibleSections } from "../nav";
import { cx } from "./ui";

type Theme = "light" | "dark" | "system";

function loadTheme(): Theme {
  try {
    const v = localStorage.getItem("obs-theme");
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function applyTheme(theme: Theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(loadTheme);
  useEffect(() => {
    applyTheme(theme);
    try {
      if (theme === "system") localStorage.removeItem("obs-theme");
      else localStorage.setItem("obs-theme", theme);
    } catch {
      /* storage unavailable: the theme still applies for this page view */
    }
  }, [theme]);
  const dark = theme === "dark" || (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  return (
    <button
      type="button"
      className="rounded p-2 hover:bg-subtle"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setTheme(dark ? "light" : "dark")}
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

export function Layout() {
  const { me, can, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const sections = visibleSections(can);
  const Brand = BRAND_ICON;

  return (
    <div className="flex h-full">
      <aside
        className={cx(
          "fixed inset-y-0 left-0 z-30 w-64 transform border-r border-line bg-surface transition-transform md:static md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 items-center gap-2 border-b border-line px-4">
          <Brand className="h-5 w-5 text-brand" aria-hidden />
          <span className="truncate text-sm font-semibold">{me?.instance_name}</span>
        </div>
        <nav aria-label="Main" className="space-y-5 overflow-y-auto p-3">
          {sections.map((s) => (
            <div key={s.title ?? "main"}>
              {s.title && <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted">{s.title}</p>}
              <ul className="space-y-0.5">
                {s.items.map((i) => (
                  <li key={i.to}>
                    <NavLink
                      to={i.to}
                      end={i.to === "/"}
                      onClick={() => setOpen(false)}
                      className={({ isActive }) =>
                        cx("flex items-center gap-2 rounded-md px-3 py-2 text-sm", isActive ? "bg-brand/10 font-medium text-brand" : "hover:bg-subtle")
                      }
                    >
                      <i.icon className="h-4 w-4" aria-hidden />
                      {i.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
      {open && <button type="button" aria-label="Close menu" className="fixed inset-0 z-20 bg-black/40 md:hidden" onClick={() => setOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-line bg-surface px-4">
          <button type="button" className="rounded p-2 hover:bg-subtle md:hidden" aria-label="Open menu" onClick={() => setOpen(true)}>
            <Menu className="h-5 w-5" />
          </button>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <button type="button" onClick={() => navigate("/account")} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-subtle">
              <UserCircle className="h-5 w-5" aria-hidden />
              <span className="hidden sm:inline">{me?.user.username}</span>
              <span className="hidden text-xs text-muted sm:inline">({me?.user.role.name})</span>
            </button>
            <button
              type="button"
              className="rounded p-2 hover:bg-subtle"
              aria-label="Sign out"
              onClick={() => void logout().then(() => navigate("/login"))}
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
