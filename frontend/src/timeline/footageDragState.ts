/** Set true while dragging from MediaBin (Safari may omit custom MIME in dragOver.types). */
let footageFromBinActive = false;

export function setFootageFromBinDragging(active: boolean): void {
  footageFromBinActive = active;
}

export function isFootageFromBinDragging(): boolean {
  return footageFromBinActive;
}
