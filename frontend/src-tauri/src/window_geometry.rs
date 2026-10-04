#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WorkArea {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WindowBounds {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

pub fn clamp_saved_bounds(
    saved: WindowBounds,
    area: WorkArea,
    default_size: (u32, u32),
) -> Option<WindowBounds> {
    if area.width == 0 || area.height == 0 {
        return None;
    }
    let min_width = 320.min(area.width);
    let min_height = 240.min(area.height);
    let width = if saved.width == 0 {
        default_size.0
    } else {
        saved.width
    }
    .clamp(min_width, area.width);
    let height = if saved.height == 0 {
        default_size.1
    } else {
        saved.height
    }
    .clamp(min_height, area.height);
    let max_x = ((area.x as i64 + area.width as i64 - width as i64)
        .max(area.x as i64)
        .min(i32::MAX as i64)) as i32;
    let max_y = ((area.y as i64 + area.height as i64 - height as i64)
        .max(area.y as i64)
        .min(i32::MAX as i64)) as i32;
    Some(WindowBounds {
        x: saved.x.clamp(area.x, max_x),
        y: saved.y.clamp(area.y, max_y),
        width,
        height,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn offscreen_bounds_fit_the_nearest_usable_area_without_underflow() {
        let area = WorkArea {
            x: -1920,
            y: 40,
            width: 1200,
            height: 760,
        };
        let bounds = clamp_saved_bounds(
            WindowBounds {
                x: -5000,
                y: -3000,
                width: 1600,
                height: 1000,
            },
            area,
            (1440, 900),
        )
        .unwrap();
        assert_eq!(
            bounds,
            WindowBounds {
                x: -1920,
                y: 40,
                width: 1200,
                height: 760
            }
        );
    }

    #[test]
    fn small_work_areas_clamp_to_the_available_size_and_keep_titlebar_visible() {
        let area = WorkArea {
            x: 40,
            y: 30,
            width: 600,
            height: 400,
        };
        let bounds = clamp_saved_bounds(
            WindowBounds {
                x: 900,
                y: -600,
                width: 1440,
                height: 900,
            },
            area,
            (1440, 900),
        )
        .unwrap();
        assert_eq!(
            bounds,
            WindowBounds {
                x: 40,
                y: 30,
                width: 600,
                height: 400
            }
        );
        assert!(bounds.y >= area.y);
        assert!(bounds.y + 48 <= area.y + area.height as i32);
    }

    #[test]
    fn normal_saved_bounds_are_preserved_and_empty_areas_are_rejected() {
        let area = WorkArea {
            x: 0,
            y: 0,
            width: 1920,
            height: 1080,
        };
        let saved = WindowBounds {
            x: 100,
            y: 80,
            width: 1440,
            height: 900,
        };
        assert_eq!(clamp_saved_bounds(saved, area, (1440, 900)), Some(saved));
        assert_eq!(
            clamp_saved_bounds(saved, WorkArea { width: 0, ..area }, (1440, 900)),
            None
        );
    }
}
