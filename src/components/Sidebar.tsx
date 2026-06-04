import {
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  GitBranch,
  History,
  Home,
  Inbox,
  RefreshCcw,
  Settings,
  TableProperties
} from "lucide-react";
import { Layout, Menu } from "antd";
import type { MenuProps } from "antd";

const { Sider } = Layout;

export type NavPage =
  | "dashboard"
  | "sources"
  | "queue"
  | "document-review"
  | "rule-review"
  | "field-review"
  | "mapping-review"
  | "submissions"
  | "results"
  | "activity"
  | "settings";

const NAV_ITEMS: MenuProps["items"] = [
  { key: "dashboard", icon: <Home size={16} />, label: "Dashboard" },
  { key: "sources", icon: <BookOpen size={16} />, label: "Sources" },
  { key: "queue", icon: <RefreshCcw size={16} />, label: "Queue" },
  { type: "divider" },
  { key: "document-review", icon: <FileSearch size={16} />, label: "Document Review" },
  { key: "rule-review", icon: <GitBranch size={16} />, label: "Rules" },
  { key: "field-review", icon: <CheckCircle2 size={16} />, label: "Fields" },
  { key: "mapping-review", icon: <TableProperties size={16} />, label: "Mappings" },
  { type: "divider" },
  { key: "submissions", icon: <Inbox size={16} />, label: "Submissions" },
  { key: "results", icon: <ClipboardCheck size={16} />, label: "Results" },
  { type: "divider" },
  { key: "activity", icon: <History size={16} />, label: "Activity" },
  { key: "settings", icon: <Settings size={16} />, label: "Settings" },
];

export function Sidebar({
  activePage,
  onNavigate,
}: {
  activePage: NavPage;
  onNavigate: (page: NavPage) => void;
}) {
  return (
    <Sider
      className="app-sidebar"
      width={220}
      style={{
        background: "#001529",
        height: "100vh",
        position: "fixed",
        left: 0,
        top: 0,
        bottom: 0,
        overflow: "auto",
      }}
    >
      <div
        className="sidebar-brand"
        style={{
          height: 82,
          display: "flex",
          alignItems: "center",
          padding: "12px 18px",
        }}
      >
        <img src="/hkpc-logo.svg" alt="HKPC" />
      </div>
      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[activePage]}
        items={NAV_ITEMS}
        onClick={({ key }) => onNavigate(key as NavPage)}
        style={{ background: "transparent", borderInlineEnd: "none" }}
      />
    </Sider>
  );
}
