import clsx from "clsx";
import { ChevronDown, ExternalLink, LogOut, UserCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useModules, usePlatformName } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { NAV, type NavSection } from "./nav";

const WORKSPACE_KEY = "opsbrain.workspace";

/** A Logging or Monitoring workspace opened in its own window shows only that workspace's navigation. */
export function useWorkspace(): string | null {
  const location = useLocation();
  const [ws, setWs] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(WORKSPACE_KEY);
    } catch {
      return null;
    }
  });
  useEffect(() => {
    const requested = new URLSearchParams(location.search).get("workspace");
    if (requested && NAV.some((s) => s.key === requested && s.workspace)) {
      try {
        sessionStorage.setItem(WORKSPACE_KEY, requested);
      } catch {
        /* storage unavailable: workspace mode lasts for this page view only */
      }
      setWs(requested);
    }
  }, [location.search]);
  return ws;
}

export function openWorkspaceWindow(section: NavSection) {
  const first = section.items[0]?.path ?? "/";
  window.open(`${first}?workspace=${section.key}`, `opsbrain-${section.key}`, "noopener");
}

function Section({ section, open, toggle, installed }: {
  section: NavSection;
  open: boolean;
  toggle: () => void;
  installed: boolean | undefined;
}) {
  const { can } = useAuth();
  const items = section.items.filter((i) => can(i.permission));
  if (items.length === 0) return null;
  const Icon = section.icon;
  if (items.length === 1 && section.items.length === 1) {
    return (
      <NavLink
        to={items[0].path}
        end
        className={({ isActive }) =>
          clsx("flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
            isActive ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800/60 hover:text-white")
        }
      >
        <Icon className="h-4 w-4" aria-hidden /> {section.label}
      </NavLink>
    );
  }
  return (
    <div>
      <div className="flex items-center">
        <button onClick={toggle} aria-expanded={open}
          className="flex flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-slate-300 hover:bg-slate-800/60 hover:text-white">
          <Icon className="h-4 w-4" aria-hidden />
          <span className="flex-1">{section.label}</span>
          {section.module && installed === false && (
            <span className="rounded bg-slate-700 px-1 text-[10px] uppercase text-slate-300">off</span>
          )}
          <ChevronDown className={clsx("h-3.5 w-3.5 transition", open ? "" : "-rotate-90")} aria-hidden />
        </button>
        {section.workspace && (
          <button onClick={() => openWorkspaceWindow(section)} title={`Open ${section.label} in a new window`}
            aria-label={`Open ${section.label} in a new window`}
            className="ml-0.5 rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white">
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {open && (
        <div className="ml-4 mt-0.5 space-y-0.5 border-l border-slate-700 pl-2">
          {items.map((item) => (
            <NavLink key={item.path} to={item.path} end
              className={({ isActive }) =>
                clsx("block rounded px-2 py-1 text-[13px]",
                  isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-800/60 hover:text-white")
              }>
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AppLayout() {
  const { auth, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const workspace = useWorkspace();
  const platformName = usePlatformName();
  const modules = useModules();
  const installed = new Map(modules.data?.modules.map((m) => [m.key, m.installed]));
  const sections = workspace ? NAV.filter((s) => s.key === workspace) : NAV;
  const activeSection = NAV.find((s) => s.items.some((i) => i.path === location.pathname))?.key;
  const [openSections, setOpenSections] = useState<Set<string>>(() => new Set(activeSection ? [activeSection] : []));
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (activeSection) setOpenSections((prev) => (prev.has(activeSection) ? prev : new Set(prev).add(activeSection)));
  }, [activeSection]);
  useEffect(() => {
    const ws = workspace ? NAV.find((s) => s.key === workspace)?.label : null;
    document.title = ws ? `${ws} · ${platformName}` : platformName;
  }, [workspace, platformName]);

  const toggle = (key: string) =>
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col bg-slate-900">
        <Link to={workspace ? NAV.find((s) => s.key === workspace)!.items[0].path : "/"}
          className="flex items-center gap-2 px-4 py-4 text-white">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <div className="leading-tight">
            <div className="text-sm font-semibold">{platformName}</div>
            <div className="text-[11px] text-slate-400">
              {workspace ? `${NAV.find((s) => s.key === workspace)?.label} workspace` : "Observability Platform"}
            </div>
          </div>
        </Link>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4" aria-label="Main">
          {sections.map((s) => (
            <Section key={s.key} section={s} open={workspace !== null || openSections.has(s.key)}
              toggle={() => toggle(s.key)} installed={s.module ? installed.get(s.module) : undefined} />
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-end gap-3 border-b border-slate-200 bg-white px-4">
          <div className="relative">
            <button onClick={() => setMenuOpen((o) => !o)} aria-expanded={menuOpen}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-slate-700 hover:bg-slate-100">
              <UserCircle className="h-5 w-5" aria-hidden />
              {auth?.user?.username}
              <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            </button>
            {menuOpen && (
              <div className="absolute right-0 z-40 mt-1 w-48 rounded-md border border-slate-200 bg-white py-1 shadow-lg"
                onMouseLeave={() => setMenuOpen(false)}>
                <div className="border-b border-slate-100 px-3 py-1.5 text-xs text-slate-500">
                  {auth?.user?.roles.join(", ")}
                </div>
                <Link to="/profile" onClick={() => setMenuOpen(false)}
                  className="block px-3 py-1.5 text-sm hover:bg-slate-50">My account</Link>
                <button className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                  onClick={async () => {
                    await logout();
                    navigate("/login");
                  }}>
                  <LogOut className="h-4 w-4" aria-hidden /> Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
