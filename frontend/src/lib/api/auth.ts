import { ApiError, request } from "./client";

export interface User {
  id: string;
  username: string;
}

export interface AuthConfig {
  signup_enabled: boolean;
}

export const getAuthConfig = () => request<AuthConfig>("GET", "/auth/config");

export const login = (username: string, password: string) =>
  request<User>("POST", "/auth/login", { username, password });

export const signup = (username: string, password: string) =>
  request<User>("POST", "/auth/signup", { username, password });

export const logout = () => request<void>("POST", "/auth/logout");

/** The logged-in user, or null when there is no valid session. */
export async function me(): Promise<User | null> {
  try {
    return await request<User>("GET", "/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}
