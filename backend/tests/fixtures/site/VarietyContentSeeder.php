<?php
/* Synthetic VarietyContentSeeder-shaped fixture: $attrs arrays with slug + content_json */
class VarietyContentSeederFixture
{
    public function run(): void
    {
        $attrs = [
            'process_category_id' => 7,
            'slug' => 'demo-meat',
            'name' => 'demo 酱卤肉旗舰',
            'is_priority' => true,
            'status' => 1,
            'content_json' => [
                /* ── 旗舰模板开关 ── */
                'is_flagship_template' => true,
                'hero' => 'demo 旗舰产线',
                'pain_section' => 'demo 痛点叙述：出品率低、保鲜期短。',
                'solution_section' => 'demo 方案叙述：无油干式爪泵 + 反压杀菌。',
                'result_section' => 'demo 成果：出品率 +8%~12%。',
            ],
        ];
        Variety::updateOrCreate(['slug' => $attrs['slug']], $attrs);
    }
}
