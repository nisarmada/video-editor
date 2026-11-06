export type FootageClip = {
  name: string;
  source: string;
  duration_seconds: number | null;
  has_proxy: boolean;
  has_thumbnail: boolean;
  proxy_url: string;
  thumbnail_url: string;
};

type FootageListResponse = {
  clips: FootageClip[];
};

export async function fetchFootageList(): Promise<FootageClip[]> {
  const res = await fetch("/api/footage");
  if (!res.ok) {
    throw new Error(`Failed to load footage (${res.status})`);
  }
  const data = (await res.json()) as FootageListResponse;
  return data.clips ?? [];
}
