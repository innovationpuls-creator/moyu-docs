import { create } from "zustand";

interface ShellUiState {
	sidebarOpen: boolean;
	setSidebarOpen(open: boolean): void;
}

/** Cross-route presentation state only; server data stays in TanStack Query. */
export const useShellUiStore = create<ShellUiState>((set) => ({
	sidebarOpen: false,
	setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
}));
