<?php
/* Synthetic ProcessLibrarySeeder-shaped fixture (short-array syntax, nested tree) */
class ProcessLibrarySeederFixture
{
    private function industries(): array
    {
        return [
            // ══════════ demo 行业（2 工艺 / 3 品种） ══════════
            [
                'slug' => 'demo-food',
                'name' => 'demo 食品加工',
                'brief' => 'demo 行业简介。',
                'color' => '#12A5A0',
                'sort' => 1,
                'categories' => [
                    [
                        'slug' => 'demo-freeze-drying', 'name' => 'demo 冻干', 'vacuum_range' => '1~100 Pa',
                        'pain' => 'demo 共性痛点 A / 痛点 B',
                        'brief' => 'demo 工艺简介。',
                        'varieties' => [
                            ['slug' => 'demo-fruits', 'name' => 'demo 冻干果蔬', 'priority' => true, 'mf' => '含水率高', 'df' => '升华控温', 'mv' => '零食赛道'],
                            ['slug' => 'demo-coffee', 'name' => 'demo 冻干咖啡', 'priority' => false],
                        ],
                    ],
                    [
                        'slug' => 'demo-cooling', 'name' => 'demo 真空冷却', 'vacuum_range' => '600 Pa ~ 80 kPa',
                        'pain' => 'demo 冷却痛点',
                        'brief' => 'demo 简介。',
                        'varieties' => [
                            ['slug' => 'demo-meat', 'name' => 'demo 酱卤肉旗舰', 'priority' => true, 'mf' => '316L 管路', 'df' => '压差控制', 'mv' => '出品率+8%'],
                        ],
                    ],
                ],
            ],
            [
                'slug' => 'demo-semi',
                'name' => 'demo 半导体',
                'brief' => 'demo。',
                'color' => '#0A5FD0',
                'sort' => 2,
                'categories' => [
                    [
                        'slug' => 'demo-etching', 'name' => 'demo 刻蚀', 'vacuum_range' => '0.01~1 Pa',
                        'pain' => 'demo 颗粒污染',
                        'brief' => 'demo。',
                        'varieties' => [
                            ['slug' => 'demo-silicon', 'name' => 'demo 硅刻蚀', 'priority' => false],
                        ],
                    ],
                ],
            ],
        ];
    }
}
